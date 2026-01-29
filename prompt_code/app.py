from __future__ import annotations

import io
import re
import random
from dataclasses import dataclass, asdict
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except Exception:
    PLAYWRIGHT_OK = False


# -----------------------------
# Utilities
# -----------------------------
LEVELS = ["Simple", "Medium", "Complex", "Expert"]

OPEN = ["Open", "Visit", "Go to", "Navigate to", "Head to"]
NEXT = ["Then", "Next", "After that", "Once you've done that"]
FIND = ["find", "locate", "open", "navigate to"]

def ensure_http(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")

def host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""

def pick(rng: random.Random, xs: List[str]) -> str:
    return rng.choice(xs)

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def normalize_for_dedupe(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# -----------------------------
# Site classification (lightweight)
# -----------------------------
def site_category_from_host(url: str) -> str:
    h = host(url)
    if h == "github.com" or "gitlab" in h or "bitbucket" in h:
        return "devplatform"
    if "aws.amazon.com" in h or "amazonaws.com" in h:
        return "cloud"
    if "cloud.google.com" in h or "console.cloud.google.com" in h:
        return "cloud"
    if "zalando." in h:
        return "ecommerce"
    # unknown -> generic; probing may refine
    return "generic"


# -----------------------------
# Probe (vocab + nav terms only; not generating combinations)
# -----------------------------
@dataclass
class Probe:
    currency: str = "$"
    cart_word: str = "cart"          # cart/bag/basket
    add_phrase: str = "add it to your cart"
    signin_word: str = "sign in"     # sign in/log in
    has_search: bool = False
    has_checkout_terms: bool = False
    guest_checkout_hint: bool = False
    nav_terms: List[str] = None
    notes: List[str] = None

def probe_site(url: str, headless: bool, timeout_ms: int) -> Probe:
    # Safe defaults
    pr = Probe(nav_terms=[], notes=[])
    if not PLAYWRIGHT_OK:
        pr.notes.append("Playwright not available; using defaults.")
        return pr

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 850}, locale="en-US")
        page = ctx.new_page()

        # Speed up: block heavy assets
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ["image", "media", "font", "stylesheet"]
            else route.continue_(),
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(900)
            html = page.content()
        except Exception as e:
            pr.notes.append(f"Probe load failed: {type(e).__name__}")
            html = ""
        finally:
            ctx.close()
            browser.close()

    soup = BeautifulSoup(html or "", "lxml")
    text = clean_text(soup.get_text(" ")).lower()

    # Currency
    if "€" in text:
        pr.currency = "€"
    elif "£" in text:
        pr.currency = "£"
    elif "$" in text:
        pr.currency = "$"

    # Cart/bag wording
    if "add to bag" in text or "shopping bag" in text:
        pr.cart_word = "bag"
        pr.add_phrase = "add it to your bag"
    elif "add to basket" in text or "basket" in text:
        pr.cart_word = "basket"
        pr.add_phrase = "add it to your basket"
    else:
        pr.cart_word = "cart"
        pr.add_phrase = "add it to your cart"

    # Sign-in wording
    if "log in" in text or "login" in text:
        pr.signin_word = "log in"
    if "sign in" in text:
        pr.signin_word = "sign in"

    # Feature hints
    pr.has_search = ("type=\"search\"" in (html or "").lower()) or ("search" in text)
    pr.has_checkout_terms = ("checkout" in text) or ("shipping" in text) or ("delivery" in text)
    pr.guest_checkout_hint = ("guest checkout" in text) or ("continue as guest" in text) or ("checkout as guest" in text)

    # Nav terms (used as "entities" to make prompts feel site-faithful)
    nav_terms: List[str] = []
    for a in soup.select("nav a, header a, [role='navigation'] a"):
        t = clean_text(a.get_text(" "))
        tl = t.lower()
        if not (3 <= len(t) <= 24):
            continue
        if any(x in tl for x in ["home", "menu", "search", "account", "profile", "sign in", "log in", "cart", "bag", "basket"]):
            continue
        # keep short-ish "sections"
        nav_terms.append(t)

    # Dedupe, keep order
    seen = set()
    pr.nav_terms = []
    for t in nav_terms:
        k = normalize_for_dedupe(t)
        if k not in seen:
            pr.nav_terms.append(t)
            seen.add(k)
    pr.nav_terms = pr.nav_terms[:14]

    return pr


# -----------------------------
# Shapes (distinct task types, not "same + more constraints")
# -----------------------------
@dataclass(frozen=True)
class Shape:
    id: str
    level: str
    category: str  # ecommerce/cloud/devplatform/generic
    # returns: (prompt_text, entity_label)
    make: Callable[[random.Random, Dict], Tuple[str, str]]


# Slot banks (fallback entities; not used as cross-products)
ECOM_ITEMS = ["women's trench coat", "men's hoodie", "white socks multipack", "women's blazer", "ankle boots"]
CLOUD_SERVICES = ["Amazon S3", "Amazon EC2", "AWS Lambda", "Cloud Storage", "Compute Engine", "BigQuery"]
DEV_TOPICS = ["machine learning", "web framework", "CLI tool", "data visualization", "backend", "devops"]

def auth_phrase(ctx: Dict) -> str:
    include_auth = ctx["include_auth"]
    embed = ctx["embed_creds"]
    email = ctx["email"]
    password = ctx["password"]
    signin_word = ctx["probe"].signin_word

    if not include_auth:
        return "(skip signing in if prompted)"
    if embed and email and password:
        return f"{signin_word} using email '{email}' and password '{password}'"
    return f"{signin_word} using the provided credentials"

def entity_from_nav_or_fallback(rng: random.Random, probe: Probe, fallback: List[str]) -> str:
    if probe.nav_terms:
        return pick(rng, probe.nav_terms)
    return pick(rng, fallback)

def shapes_library() -> List[Shape]:
    S: List[Shape] = []

    # ----- Ecommerce
    def ecom_policy(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and {pick(rng, FIND)} the returns/refunds policy. "
                f"Scroll until you can see the part that states the return window (number of days).",
                "returns policy")

    def ecom_browse_section(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        section = entity_from_nav_or_fallback(rng, pr, ["Women", "Men", "Shoes", "Clothing", "Accessories"])
        return (f"{pick(rng, OPEN)} {url} and navigate to '{section}' using the main menu. "
                f"Open any category page and confirm you can see filters (like size/color/price) or sorting controls.",
                section)

    def ecom_search_verify(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        q = pick(rng, ECOM_ITEMS)
        return (f"{pick(rng, OPEN)} {url}, search for '{q}', and open one product from the results. "
                f"On the product page, find where size selection is shown and note whether multiple sizes are available.",
                q)

    def ecom_cart_review(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        q = pick(rng, ECOM_ITEMS)
        return (f"{pick(rng, OPEN)} {url}, search for '{q}', open a product, and {pr.add_phrase}. "
                f"{pick(rng, NEXT)} open your {pr.cart_word} and verify the item name is visible there.",
                q)

    def ecom_checkout_stop(rng, ctx):
        url, pr, persona = ctx["url"], ctx["probe"], ctx["persona"]
        q = "women's trench coat"
        cap = f"{pr.currency}200"
        guest = "as a guest" if pr.guest_checkout_hint else "(choose guest checkout if available)"
        addr = f"{persona['name']}, {persona['street']}, {persona['zip']} {persona['city']}, {persona['country']}"
        return (f"{pick(rng, OPEN)} {url}, search for '{q}', and filter for a price under {cap} (and size 'S' if available). "
                f"Open the first result, {pr.add_phrase}, and proceed to checkout {guest}. "
                f"Fill the delivery address with: {addr}. Continue until you reach the payment selection page, then stop.",
                q)

    def ecom_recovery_relax_one(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        return (f"{pick(rng, OPEN)} {url} and search for 'women's trench coat'. Apply a very strict filter (e.g., price under {pr.currency}80). "
                f"If there are no suitable results, relax exactly ONE constraint (only the price, or only the size) until you can open a valid product page.",
                "recovery")

    S += [
        Shape("ecom_policy", "Simple", "ecommerce", ecom_policy),
        Shape("ecom_browse_section", "Simple", "ecommerce", ecom_browse_section),
        Shape("ecom_search_verify", "Medium", "ecommerce", ecom_search_verify),
        Shape("ecom_cart_review", "Complex", "ecommerce", ecom_cart_review),
        Shape("ecom_checkout_stop", "Complex", "ecommerce", ecom_checkout_stop),
        Shape("ecom_recovery_relax_one", "Expert", "ecommerce", ecom_recovery_relax_one),
    ]

    # ----- Cloud
    def cloud_find_pricing(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        svc = entity_from_nav_or_fallback(rng, pr, CLOUD_SERVICES)
        return (f"{pick(rng, OPEN)} {url} and find the pricing page for '{svc}'. "
                f"Locate one concrete pricing unit (for example: per GB-month, per request, per vCPU-hour).",
                svc)

    def cloud_find_quotas(rng, ctx):
        url = ctx["url"]
        svc = pick(rng, CLOUD_SERVICES)
        return (f"{pick(rng, OPEN)} {url} and search for '{svc} quotas' (or 'limits'). "
                f"Open the official documentation page and find one default quota value.",
                svc)

    def cloud_quickstart_until_prereq(rng, ctx):
        url = ctx["url"]
        svc = pick(rng, CLOUD_SERVICES)
        return (f"{pick(rng, OPEN)} {url} and find a 'Getting started' or 'Quickstart' guide for '{svc}'. "
                f"Follow it until you reach the prerequisites section, then stop.",
                svc)

    def cloud_console_readonly(rng, ctx):
        url = ctx["url"]
        svc = pick(rng, CLOUD_SERVICES)
        return (f"{pick(rng, OPEN)} {url} and go to the cloud console/dashboard. {auth_phrase(ctx)} if prompted. "
                f"Navigate to '{svc}' and stop once you can see the service landing page. Do not create resources.",
                svc)

    def cloud_troubleshoot(rng, ctx):
        url = ctx["url"]
        svc = pick(rng, CLOUD_SERVICES)
        return (f"{pick(rng, OPEN)} {url} and search for '{svc} troubleshooting'. "
                f"Open an official troubleshooting article and navigate to a specific error or resolution section.",
                svc)

    S += [
        Shape("cloud_find_pricing", "Simple", "cloud", cloud_find_pricing),
        Shape("cloud_quickstart_until_prereq", "Medium", "cloud", cloud_quickstart_until_prereq),
        Shape("cloud_find_quotas", "Complex", "cloud", cloud_find_quotas),
        Shape("cloud_troubleshoot", "Complex", "cloud", cloud_troubleshoot),
        Shape("cloud_console_readonly", "Expert", "cloud", cloud_console_readonly),
    ]

    # ----- Dev platform
    def dev_search_topic(rng, ctx):
        url, pr = ctx["url"], ctx["probe"]
        topic = entity_from_nav_or_fallback(rng, pr, DEV_TOPICS)
        return (f"{pick(rng, OPEN)} {url} and use the site search to find repositories related to '{topic}'. "
                f"Open one repository result and locate the README.",
                topic)

    def dev_issues_filter(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and open a popular repository (any). Go to Issues and filter by label 'bug'. "
                f"Open one issue from the filtered list.",
                "issues:bug")

    def dev_pr_checks(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and open a repository with open pull requests. "
                f"Open one PR and locate the checks/status (CI) section.",
                "pull requests")

    def dev_auth_settings(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and {auth_phrase(ctx)}. "
                f"Navigate to account settings and find where security options are managed (SSH keys, sessions, or 2FA). Stop there.",
                "account security")

    S += [
        Shape("dev_search_topic", "Simple", "devplatform", dev_search_topic),
        Shape("dev_issues_filter", "Medium", "devplatform", dev_issues_filter),
        Shape("dev_pr_checks", "Complex", "devplatform", dev_pr_checks),
        Shape("dev_auth_settings", "Expert", "devplatform", dev_auth_settings),
    ]

    # ----- Generic fallback
    def gen_privacy(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and find the Privacy Policy page. Locate the section about cookies or tracking.",
                "privacy policy")

    def gen_pricing_compare(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and find a Pricing/Plans page. Identify at least two plans and one difference between them.",
                "pricing")

    def gen_support_to_contact(rng, ctx):
        url = ctx["url"]
        return (f"{pick(rng, OPEN)} {url} and find the Help/Support area. Open one help article, then navigate to the Contact page.",
                "support→contact")

    def gen_no_results_recovery(rng, ctx):
        url = ctx["url"]
        nonsense = pick(rng, ["xyzzy-123-nonexistent", "qwerty-000-nope", "asdf-9999-null"])
        return (f"{pick(rng, OPEN)} {url} and use the site search to search for '{nonsense}' to trigger a no-results page. "
                f"Then adjust the query to something sensible (like 'pricing' or 'support') and open a relevant result.",
                "no-results recovery")

    S += [
        Shape("gen_privacy", "Simple", "generic", gen_privacy),
        Shape("gen_pricing_compare", "Medium", "generic", gen_pricing_compare),
        Shape("gen_support_to_contact", "Complex", "generic", gen_support_to_contact),
        Shape("gen_no_results_recovery", "Expert", "generic", gen_no_results_recovery),
    ]

    return S


# -----------------------------
# Prompt generation (non-combinatorial selection + dedupe)
# -----------------------------
def allocate_counts(total: int, per_level: Dict[str, int]) -> Dict[str, int]:
    specified = sum(per_level.values())
    if specified > 0:
        # If user overspecifies, scale down proportionally
        if specified > total:
            scale = total / specified
            scaled = {k: int(per_level[k] * scale) for k in LEVELS}
            # fix rounding
            while sum(scaled.values()) < total:
                for k in ["Medium", "Complex", "Expert", "Simple"]:
                    scaled[k] += 1
                    if sum(scaled.values()) == total:
                        break
            return scaled
        # If underspecified, keep as is and fill remaining evenly
        out = dict(per_level)
        remain = total - specified
        i = 0
        order = ["Medium", "Complex", "Simple", "Expert"]
        while remain > 0:
            out[order[i % 4]] += 1
            i += 1
            remain -= 1
        return out

    # Auto distribution if nothing specified
    base = total // 4
    out = {
        "Simple": max(1, base),
        "Medium": max(1, base),
        "Complex": max(1, base),
        "Expert": max(1, total - 3 * max(1, base)),
    }
    # Adjust to exact total
    while sum(out.values()) < total:
        out["Medium"] += 1
    while sum(out.values()) > total:
        for k in ["Expert", "Simple", "Complex", "Medium"]:
            if out[k] > 1:
                out[k] -= 1
                break
    return out

def generate_prompts(
    url: str,
    category: str,
    probe: Probe,
    total: int,
    counts: Dict[str, int],
    seed: int,
    persona: Dict[str, str],
    include_auth: bool,
    embed_creds: bool,
    email: str,
    password: str,
) -> pd.DataFrame:
    rng = random.Random(seed)
    ctx = {
        "url": url,
        "probe": probe,
        "persona": persona,
        "include_auth": include_auth,
        "embed_creds": embed_creds,
        "email": email,
        "password": password,
    }

    all_shapes = shapes_library()

    # Use category shapes + a small amount of generic for variety on unknown sites
    cat_shapes = [s for s in all_shapes if s.category == category]
    gen_shapes = [s for s in all_shapes if s.category == "generic"]
    usable = cat_shapes if cat_shapes else gen_shapes

    # If category is not generic, sprinkle a couple generic "safe" shapes
    if category != "generic":
        usable = usable + [s for s in gen_shapes if s.level in ("Simple", "Medium")]

    # Filter out auth shapes when auth disabled (we tag them by containing "auth" in id)
    if not include_auth:
        usable = [s for s in usable if "auth" not in s.id]

    by_level: Dict[str, List[Shape]] = {lvl: [] for lvl in LEVELS}
    for s in usable:
        by_level[s.level].append(s)

    rows = []
    used_keys = set()     # (level, shape_id, entity_norm)
    used_text = set()     # prompt text norm

    for lvl in LEVELS:
        need = counts.get(lvl, 0)
        pool = by_level.get(lvl, [])[:]
        rng.shuffle(pool)

        # If user requests more than available shapes, we will reuse shapes but still dedupe by entity/text where possible.
        attempts = 0
        while len([r for r in rows if r["level"] == lvl]) < need and attempts < 400:
            attempts += 1
            if not pool:
                pool = by_level.get(lvl, [])[:]
                rng.shuffle(pool)
                if not pool:
                    break

            shape = pool[attempts % len(pool)]
            prompt, entity = shape.make(rng, ctx)
            prompt = prompt.strip()
            ent_norm = normalize_for_dedupe(entity)

            key = (lvl, shape.id, ent_norm)
            pnorm = normalize_for_dedupe(prompt)

            if key in used_keys:
                continue
            if pnorm in used_text:
                continue

            used_keys.add(key)
            used_text.add(pnorm)
            rows.append({
                "level": lvl,
                "shape_id": shape.id,
                "entity": entity,
                "prompt": prompt
            })

            if len(rows) >= total:
                break

    df = pd.DataFrame(rows)
    return df


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Non-combinatorial Prompt Generator", layout="wide")
st.title("Non-combinatorial, site-faithful prompt generator")

url_in = st.text_input("Website URL", value="https://en.zalando.de")
url = ensure_http(url_in)

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    seed = st.number_input("Seed", min_value=0, value=7, step=1)
with col2:
    total = st.number_input("Total prompts", min_value=1, value=12, step=1)
with col3:
    category_guess = site_category_from_host(url) if url else "generic"
    st.write(f"Detected category (host-based): **{category_guess}**")

with st.expander("Counts per level (optional)", expanded=False):
    st.caption("Leave all zeros to auto-distribute. If totals don't match, the app will scale/fill to reach Total prompts.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_simple = st.number_input("Simple", min_value=0, value=0, step=1)
    with c2:
        n_medium = st.number_input("Medium", min_value=0, value=0, step=1)
    with c3:
        n_complex = st.number_input("Complex", min_value=0, value=0, step=1)
    with c4:
        n_expert = st.number_input("Expert", min_value=0, value=0, step=1)

with st.sidebar:
    st.header("Probe (optional)")
    use_probe = st.toggle("Use Playwright probe (vocab + nav terms)", value=True)
    headless = st.checkbox("Headless", value=True, disabled=not use_probe)
    timeout_ms = st.slider("Timeout (ms)", 5000, 45000, 20000, 1000, disabled=not use_probe)
    if use_probe and not PLAYWRIGHT_OK:
        st.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")

    st.header("Auth prompts")
    include_auth = st.checkbox("Include auth-gated shapes", value=True)
    embed_creds = st.checkbox("Embed credentials into prompt text", value=False)
    email = st.text_input("Email/username", value="testuser@example.com")
    password = st.text_input("Password", type="password", value="TestPass123")

    st.header("Checkout persona (for ecommerce shapes)")
    pname = st.text_input("Name", value="Jane Doe")
    pstreet = st.text_input("Street", value="Example Street 123")
    pzip = st.text_input("ZIP", value="12345")
    pcity = st.text_input("City", value="Berlin")
    pcountry = st.text_input("Country", value="Germany")

persona = {"name": pname, "street": pstreet, "zip": pzip, "city": pcity, "country": pcountry}

per_level_in = {"Simple": int(n_simple), "Medium": int(n_medium), "Complex": int(n_complex), "Expert": int(n_expert)}
counts = allocate_counts(int(total), per_level_in)

if st.button("Generate prompts", type="primary"):
    if not url:
        st.error("Please enter a URL.")
        st.stop()

    category = site_category_from_host(url)

    # Probe can refine category slightly (optional heuristic)
    probe = Probe(nav_terms=[], notes=[])
    if use_probe:
        with st.spinner("Probing site vocabulary and navigation terms..."):
            probe = probe_site(url, headless=headless, timeout_ms=int(timeout_ms))

        # If host was generic but page text strongly suggests ecommerce/dev/cloud, adjust category
        if category == "generic":
            text_hints = " ".join(probe.notes or [])
            # (We already computed has_checkout_terms/has_search; use those)
            if probe.has_checkout_terms:
                category = "ecommerce"
            elif "github" in host(url):
                category = "devplatform"

    df = generate_prompts(
        url=url,
        category=category,
        probe=probe,
        total=int(total),
        counts=counts,
        seed=int(seed),
        persona=persona,
        include_auth=include_auth,
        embed_creds=embed_creds,
        email=email,
        password=password,
    )

    st.write(f"Category used: **{category}**")
    if use_probe:
        with st.expander("Probe result (debug)", expanded=False):
            st.json(asdict(probe))

    if df.empty:
        st.warning("No prompts generated (try increasing Total or enabling more shapes/auth).")
        st.stop()

    st.subheader("Generated prompts")
    st.dataframe(df[["level", "shape_id", "entity", "prompt"]], use_container_width=True, hide_index=True)

    st.subheader("Bulk copy")
    bulk = "\n\n".join(df["prompt"].tolist())
    st.text_area("All prompts", value=bulk, height=260)

    st.subheader("Download")
    st.download_button(
        "Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="prompts.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download TXT",
        data=bulk.encode("utf-8"),
        file_name="prompts.txt",
        mime="text/plain",
    )
