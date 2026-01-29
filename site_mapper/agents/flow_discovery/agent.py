"""
Flow Discovery Agent v2.0

Discovers user flows from a site map by matching against known patterns
and optionally using LLM to discover new patterns.

Key Features:
- Pattern matching from patterns.json (code-first, grounded)
- LLM discovery for unknown flows (minimal usage)
- User approval workflow for new patterns

Improvements v2.0:
- Element Type Weighting: Buttons, search, cart get higher weights
- URL Pattern Analysis: Smart URL parsing for page types
- Semantic Matching: Embeddings for meaning-based similarity
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum

# Try to import sentence-transformers for semantic matching
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False


class FlowType(Enum):
    HAPPY_PATH = "happy_path"
    PARTIAL_FLOW = "partial_flow"


@dataclass
class UserFlow:
    """Represents a discovered user flow."""
    id: str
    name: str
    pattern_id: str
    flow_type: FlowType
    steps: List[Dict[str, Any]]
    elements: List[str]
    pages: List[str]
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "pattern_id": self.pattern_id,
            "flow_type": self.flow_type.value,
            "steps": self.steps,
            "elements": self.elements,
            "pages": self.pages,
            "confidence": self.confidence,
            "evidence": self.evidence
        }


@dataclass 
class DiscoveryResult:
    """Result from flow discovery."""
    flows: List[UserFlow]
    new_patterns_pending: List[Dict]  # Patterns waiting for user approval
    stats: Dict[str, Any]


class FlowDiscoveryAgent:
    """
    Discovers user flows from a site map.
    
    v2.0 Features:
    - Element Type Weighting
    - Smart URL Pattern Analysis
    - Semantic Matching (optional)
    
    Confidence scoring formula:
    - Element Score: 40% (with type weighting)
    - URL Score: 20% (smart parsing)
    - Semantic Score: 30% (if available, else distributed)
    - Context Bonus: 10%
    """
    
    # Confidence weights
    ELEMENT_WEIGHT = 0.40
    URL_WEIGHT = 0.20
    SEMANTIC_WEIGHT = 0.30
    CONTEXT_WEIGHT = 0.10
    CONFIDENCE_THRESHOLD = 0.7
    
    # Element type weights (stronger signals get higher weight)
    ELEMENT_TYPE_WEIGHTS = {
        "search": 2.0,      # Search boxes are very strong signals
        "button": 1.5,      # Buttons indicate actions
        "form": 1.4,        # Forms indicate data input
        "input": 1.2,       # Input fields
        "link": 1.0,        # Standard links
        "dropdown": 1.3,    # Dropdowns often indicate filter/sort
        "checkbox": 1.1,    # Checkboxes for filters
        "select": 1.3,      # Select boxes
    }
    
    # High-value keywords that boost scores
    HIGH_VALUE_KEYWORDS = {
        "cart": 2.0, "checkout": 2.0, "buy": 1.8, "purchase": 1.8,
        "login": 1.8, "signin": 1.8, "signup": 1.8, "register": 1.7,
        "search": 1.8, "filter": 1.5, "sort": 1.4,
        "book": 1.7, "reserve": 1.7, "schedule": 1.5,
        "submit": 1.5, "save": 1.3, "add": 1.3,
        "profile": 1.4, "settings": 1.4, "account": 1.4,
    }
    
    def __init__(
        self, 
        patterns_path: Optional[Path] = None, 
        llm_client: Optional[Any] = None,
        use_semantic: bool = True
    ):
        """
        Initialize the Flow Discovery Agent.
        
        Args:
            patterns_path: Path to patterns.json file
            llm_client: LLM client for discovering new patterns (optional)
            use_semantic: Enable semantic matching (requires sentence-transformers)
        """
        if patterns_path is None:
            patterns_path = Path(__file__).parent.parent / "patterns.json"
        
        self.patterns_path = patterns_path
        self.llm_client = llm_client
        self.patterns = self._load_patterns()
        self._pending_patterns: List[Dict] = []
        
        # Initialize semantic model if available and requested
        self._embedder = None
        self._pattern_embeddings: Dict[str, Any] = {}
        self.use_semantic = use_semantic and SEMANTIC_AVAILABLE
        
        if self.use_semantic:
            try:
                self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
                self._precompute_pattern_embeddings()
            except Exception:
                self.use_semantic = False
    
    def _precompute_pattern_embeddings(self):
        """Precompute embeddings for all pattern elements."""
        if not self._embedder:
            return
            
        for pattern_id, pattern in self._get_all_patterns().items():
            elements = pattern.get("elements", [])
            if elements:
                # Create a combined description for the pattern
                pattern_text = f"{pattern.get('name', '')} {pattern.get('description', '')} {' '.join(elements)}"
                self._pattern_embeddings[pattern_id] = self._embedder.encode(pattern_text)
    
    def _load_patterns(self) -> Dict:
        """Load patterns from JSON file."""
        try:
            with open(self.patterns_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"core_patterns": {}, "learned_patterns": {}}
    
    def _save_patterns(self):
        """Save patterns to JSON file."""
        with open(self.patterns_path, 'w') as f:
            json.dump(self.patterns, f, indent=2)
    
    def _get_all_patterns(self) -> Dict[str, Dict]:
        """Get combined core + learned patterns."""
        all_patterns = {}
        all_patterns.update(self.patterns.get("core_patterns", {}))
        # Only include approved learned patterns
        for pid, pattern in self.patterns.get("learned_patterns", {}).items():
            if pattern.get("approved", False):
                all_patterns[pid] = pattern
        return all_patterns
    
    def _extract_element_info(self, element_str: str) -> Tuple[str, str, float]:
        """
        Extract element type, text, and calculate weight.
        
        Input: "button: Sign in (button.HeaderMenu-link)"
        Returns: ("button", "sign in", 1.5)
        """
        element_lower = element_str.lower()
        
        # Extract type from format "type: text (selector)"
        element_type = "unknown"
        for etype in self.ELEMENT_TYPE_WEIGHTS.keys():
            if element_lower.startswith(f"{etype}:") or f"[{etype}]" in element_lower:
                element_type = etype
                break
        
        weight = self.ELEMENT_TYPE_WEIGHTS.get(element_type, 1.0)
        
        # Boost for high-value keywords
        for keyword, kw_weight in self.HIGH_VALUE_KEYWORDS.items():
            if keyword in element_lower:
                weight *= kw_weight
                break  # Only apply one keyword boost
        
        return element_type, element_lower, weight
    
    def _calculate_element_score(self, site_elements: List[str], pattern_elements: List[str]) -> float:
        """
        Calculate element matching score with type weighting.
        
        v2.0 Features:
        - Higher weights for important element types (buttons, search)
        - Keyword boost for high-value terms (cart, checkout, login)
        - Smarter partial matching
        """
        if not pattern_elements:
            return 0.0
        
        total_weight = 0
        matched_weight = 0
        
        # Process each pattern element
        for pattern_elem in pattern_elements:
            pattern_lower = pattern_elem.lower()
            
            # Extract keywords from pattern
            keywords = re.split(r'[\[\]=\s\-_\(\)\.\,\:]+', pattern_lower)
            keywords = [kw for kw in keywords if len(kw) >= 3]
            
            # Base weight for this pattern element
            base_weight = 1.0
            for keyword, kw_weight in self.HIGH_VALUE_KEYWORDS.items():
                if keyword in pattern_lower:
                    base_weight = kw_weight
                    break
            
            total_weight += base_weight
            
            # Search through site elements for match
            best_match_score = 0.0
            for site_elem in site_elements:
                elem_type, elem_lower, elem_weight = self._extract_element_info(site_elem)
                
                # Direct match
                if pattern_lower in elem_lower:
                    match_score = 1.0 * elem_weight
                # Keyword match
                elif any(kw in elem_lower for kw in keywords):
                    match_score = 0.7 * elem_weight
                # Partial match
                elif any(kw[:4] in elem_lower for kw in keywords if len(kw) >= 4):
                    match_score = 0.3 * elem_weight
                else:
                    match_score = 0.0
                
                best_match_score = max(best_match_score, match_score)
            
            matched_weight += min(base_weight, best_match_score)
        
        return min(1.0, matched_weight / total_weight if total_weight > 0 else 0)
    
    def _calculate_url_score(self, site_urls: List[str], pattern_urls: List[str]) -> float:
        """
        Calculate URL pattern matching score with smart parsing.
        
        v2.0 Features:
        - Parse URL paths and query params
        - Recognize URL patterns (not just exact matches)
        - Handle wildcards in patterns
        """
        if not pattern_urls:
            return 0.0
        
        matches = 0
        
        for pattern_url in pattern_urls:
            pattern_lower = pattern_url.lower()
            
            for site_url in site_urls:
                url_lower = site_url.lower()
                
                # Direct match
                if pattern_lower in url_lower:
                    matches += 1
                    break
                
                # Path component match (e.g., "/login" in "/en/login")
                pattern_parts = pattern_lower.strip('/').split('/')
                url_parts = url_lower.split('/')
                if any(part in url_parts for part in pattern_parts if part):
                    matches += 0.7
                    break
                
                # Query param match (e.g., "?q=" in any URL)
                if pattern_lower.startswith('?'):
                    if pattern_lower in url_lower:
                        matches += 0.8
                        break
        
        return min(1.0, matches / len(pattern_urls))
    
    def _calculate_semantic_score(self, site_elements: List[str], pattern_id: str) -> float:
        """
        Calculate semantic similarity using embeddings.
        
        Compares the meaning of site elements with pattern description.
        """
        if not self.use_semantic or not self._embedder or pattern_id not in self._pattern_embeddings:
            return 0.0
        
        try:
            # Combine site elements into a single text
            site_text = " ".join([e.split(":")[-1].strip() if ":" in e else e for e in site_elements[:50]])
            
            if not site_text.strip():
                return 0.0
            
            # Get embeddings
            site_embedding = self._embedder.encode(site_text)
            pattern_embedding = self._pattern_embeddings[pattern_id]
            
            # Cosine similarity
            similarity = np.dot(site_embedding, pattern_embedding) / (
                np.linalg.norm(site_embedding) * np.linalg.norm(pattern_embedding)
            )
            
            # Normalize to 0-1 range (similarity can be negative)
            return max(0.0, min(1.0, (similarity + 1) / 2))
        except Exception:
            return 0.0
    
    def _calculate_context_bonus(self, site_elements: List[str], pattern: Dict) -> float:
        """
        Calculate context bonus based on element co-occurrence.
        
        If related elements appear together, boost confidence.
        E.g., email + password together = strong auth signal
        """
        pattern_elements = pattern.get("elements", [])
        if len(pattern_elements) < 2:
            return 0.0
        
        site_text = " ".join(site_elements).lower()
        
        # Count how many pattern elements appear
        found_count = sum(1 for pe in pattern_elements if pe.lower() in site_text)
        
        # Bonus formula: more co-occurring elements = higher bonus
        if found_count >= 3:
            return 0.3
        elif found_count >= 2:
            return 0.15
        return 0.0
    
    def _calculate_confidence(
        self, 
        element_score: float, 
        url_score: float, 
        semantic_score: float = 0.0,
        context_bonus: float = 0.0
    ) -> float:
        """
        Calculate overall confidence score.
        
        v2.0 Formula:
        - Element Score: 40% (with type weighting)
        - URL Score: 20%
        - Semantic Score: 30% (if available)
        - Context Bonus: 10%
        
        If semantic not available, redistribute weight to elements.
        """
        if self.use_semantic:
            return (
                element_score * self.ELEMENT_WEIGHT +
                url_score * self.URL_WEIGHT +
                semantic_score * self.SEMANTIC_WEIGHT +
                context_bonus * self.CONTEXT_WEIGHT
            )
        else:
            # Redistribute semantic weight to element and url
            return (
                element_score * 0.55 +
                url_score * 0.35 +
                context_bonus * 0.10
            )
    
    def _build_flow_steps(
        self, 
        pattern_id: str, 
        pattern: Dict, 
        matched_elements: List[str],
        matched_pages: List[str]
    ) -> List[Dict]:
        """Build step-by-step flow from matched elements."""
        steps = []
        
        # Map pattern elements to actions
        action_map = {
            "search": "search",
            "login": "click",
            "sign in": "click",
            "register": "click",
            "add to cart": "click",
            "buy": "click",
            "checkout": "click",
            "filter": "select",
            "sort": "select",
            "input": "fill",
            "form": "fill",
            "submit": "click",
            "book": "click",
            "reserve": "click"
        }
        
        for elem in matched_elements[:5]:  # Limit to 5 steps
            action = "interact"
            elem_lower = elem.lower()
            for key, act in action_map.items():
                if key in elem_lower:
                    action = act
                    break
            
            steps.append({
                "action": action,
                "element": elem,
                "description": f"{action.capitalize()} on {elem.split(':')[-1].strip()[:40]}"
            })
        
        return steps if steps else [{"action": "navigate", "element": "page", "description": f"Navigate to {pattern['name']} section"}]
    
    def discover(
        self, 
        site_elements: List[str], 
        site_urls: List[str],
        include_partial: bool = True,
        use_llm: bool = False
    ) -> DiscoveryResult:
        """
        Discover user flows from site map data.
        
        Args:
            site_elements: List of element identifiers/text from crawled site
            site_urls: List of URLs from crawled site
            include_partial: Include partial flows (default True)
            use_llm: Use LLM to discover new patterns (default False)
            
        Returns:
            DiscoveryResult with discovered flows and pending patterns
        """
        flows: List[UserFlow] = []
        all_patterns = self._get_all_patterns()
        
        stats = {
            "patterns_checked": len(all_patterns),
            "patterns_matched": 0,
            "flows_discovered": 0,
            "average_confidence": 0.0,
            "semantic_enabled": self.use_semantic
        }
        
        # Match against known patterns
        for pattern_id, pattern in all_patterns.items():
            element_score = self._calculate_element_score(
                site_elements, 
                pattern.get("elements", [])
            )
            url_score = self._calculate_url_score(
                site_urls, 
                pattern.get("urls", [])
            )
            semantic_score = self._calculate_semantic_score(site_elements, pattern_id)
            context_bonus = self._calculate_context_bonus(site_elements, pattern)
            
            confidence = self._calculate_confidence(
                element_score, url_score, semantic_score, context_bonus
            )
            
            # Determine flow type
            if confidence >= self.CONFIDENCE_THRESHOLD:
                flow_type = FlowType.HAPPY_PATH
            elif confidence >= 0.3 and include_partial:
                flow_type = FlowType.PARTIAL_FLOW
            else:
                continue  # Skip low confidence patterns
            
            # Find matched elements
            matched_elements = []
            for elem in site_elements:
                elem_lower = elem.lower()
                for pe in pattern.get("elements", []):
                    if pe.lower() in elem_lower or any(
                        kw in elem_lower 
                        for kw in pe.lower().split() if len(kw) >= 3
                    ):
                        matched_elements.append(elem)
                        break
            
            # Find matched pages
            matched_pages = [
                url for url in site_urls 
                if any(pu.lower() in url.lower() for pu in pattern.get("urls", []))
            ]
            
            # Build flow
            flow = UserFlow(
                id=f"flow_{pattern_id}_{len(flows)}",
                name=pattern.get("name", pattern_id.replace("_", " ").title()),
                pattern_id=pattern_id,
                flow_type=flow_type,
                steps=self._build_flow_steps(pattern_id, pattern, matched_elements, matched_pages),
                elements=matched_elements[:10],  # Limit
                pages=matched_pages[:5],  # Limit
                confidence=round(float(confidence), 2),
                evidence={
                    "element_score": round(float(element_score), 2),
                    "url_score": round(float(url_score), 2),
                    "semantic_score": round(float(semantic_score), 2) if self.use_semantic else None,
                    "context_bonus": round(float(context_bonus), 2),
                    "pattern_source": "core" if pattern_id in self.patterns.get("core_patterns", {}) else "learned"
                }
            )
            
            flows.append(flow)
            stats["patterns_matched"] += 1
        
        # Sort flows by confidence (highest first)
        flows.sort(key=lambda f: f.confidence, reverse=True)
        
        stats["flows_discovered"] = len(flows)
        if flows:
            stats["average_confidence"] = round(
                sum(f.confidence for f in flows) / len(flows), 2
            )
        
        return DiscoveryResult(
            flows=flows,
            new_patterns_pending=self._pending_patterns,
            stats=stats
        )
    
    def approve_pattern(self, pattern_id: str, pattern_data: Dict) -> bool:
        """
        Approve a discovered pattern and add to learned patterns.
        
        Args:
            pattern_id: Unique ID for the pattern
            pattern_data: Pattern data including elements, urls, name
            
        Returns:
            True if approved successfully
        """
        pattern_data["approved"] = True
        self.patterns["learned_patterns"][pattern_id] = pattern_data
        self._save_patterns()
        
        # Recompute embeddings for new pattern
        if self.use_semantic and self._embedder:
            self._precompute_pattern_embeddings()
        
        # Remove from pending
        self._pending_patterns = [
            p for p in self._pending_patterns if p.get("id") != pattern_id
        ]
        
        return True
    
    def reject_pattern(self, pattern_id: str) -> bool:
        """Remove a pattern from pending list."""
        self._pending_patterns = [
            p for p in self._pending_patterns if p.get("id") != pattern_id
        ]
        return True
