"""
Data Models for Site Mapper

Defines Element, Action, and SiteMap structures.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import json


class ElementType(str, Enum):
    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textarea"
    DROPDOWN = "dropdown"
    MENU = "menu"
    MODAL_TRIGGER = "modal_trigger"
    TAB = "tab"
    ACCORDION = "accordion"
    CAROUSEL = "carousel"
    FORM = "form"
    SEARCH = "search"
    FILTER = "filter"
    SORT = "sort"
    PAGINATION = "pagination"
    OTHER = "other"


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    HOVER = "hover"
    SCROLL = "scroll"
    WAIT = "wait"


class ActionResult(str, Enum):
    NAVIGATION = "navigation"  # URL changed
    MODAL_OPENED = "modal_opened"
    DROPDOWN_EXPANDED = "dropdown_expanded"
    CONTENT_CHANGED = "content_changed"
    FORM_SUBMITTED = "form_submitted"
    CART_UPDATED = "cart_updated"
    FILTER_APPLIED = "filter_applied"
    ERROR_SHOWN = "error_shown"
    NO_CHANGE = "no_change"
    UNKNOWN = "unknown"


@dataclass
class Element:
    """Represents an interactive element on a page."""
    id: str
    type: ElementType
    text: str
    selector: str
    page_url: str
    attributes: Dict[str, str] = field(default_factory=dict)
    
    # What happens when interacted with
    action_result: Optional[ActionResult] = None
    result_details: Optional[str] = None
    
    # For forms/inputs
    input_type: Optional[str] = None
    placeholder: Optional[str] = None
    options: List[str] = field(default_factory=list)
    
    # Metadata
    is_visible: bool = True
    is_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, ElementType) else self.type,
            "text": self.text,
            "selector": self.selector,
            "page_url": self.page_url,
            "attributes": self.attributes,
            "action_result": self.action_result.value if self.action_result else None,
            "result_details": self.result_details,
            "input_type": self.input_type,
            "placeholder": self.placeholder,
            "options": self.options,
        }


@dataclass
class Action:
    """An action to be executed by the crawler."""
    type: ActionType
    target: str  # Description or selector
    value: Optional[str] = None  # For type/select actions
    reason: Optional[str] = None  # Why LLM suggested this action
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "target": self.target,
            "value": self.value,
            "reason": self.reason,
        }


@dataclass
class PageState:
    """State of a page at a point in time."""
    url: str
    title: str
    element_count: int
    visible_text_preview: str  # First 500 chars
    forms_count: int = 0
    buttons_count: int = 0
    links_count: int = 0


@dataclass
class SiteMap:
    """Complete site map with all discovered elements."""
    url: str
    domain: str
    
    # Discovered elements
    elements: List[Element] = field(default_factory=list)
    
    # Pages visited
    pages: List[str] = field(default_factory=list)
    
    # User journeys discovered
    journeys: List[Dict[str, Any]] = field(default_factory=list)
    
    # Stats
    pages_crawled: int = 0
    elements_discovered: int = 0
    actions_executed: int = 0
    
    # Exploration log
    exploration_log: List[str] = field(default_factory=list)
    
    def add_element(self, element: Element):
        # Check for duplicates
        for e in self.elements:
            if e.selector == element.selector and e.page_url == element.page_url:
                return  # Already exists
        self.elements.append(element)
        self.elements_discovered = len(self.elements)
    
    def add_page(self, url: str):
        if url not in self.pages:
            self.pages.append(url)
            self.pages_crawled = len(self.pages)
    
    def log(self, message: str):
        self.exploration_log.append(message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "pages_crawled": self.pages_crawled,
            "elements_discovered": self.elements_discovered,
            "actions_executed": self.actions_executed,
            "pages": self.pages,
            "elements": [e.to_dict() for e in self.elements],
            "journeys": self.journeys,
            "exploration_log": self.exploration_log[-50:],  # Last 50 entries
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json())


# UNSAFE actions that should never be executed
UNSAFE_KEYWORDS = [
    "delete", "remove", "cancel order", "checkout", "payment", "pay now",
    "place order", "confirm purchase", "submit order", "buy now",
    "unsubscribe", "deactivate", "close account", "logout", "sign out"
]

def is_safe_action(action_text: str) -> bool:
    """Check if an action is safe to execute."""
    text_lower = action_text.lower()
    return not any(kw in text_lower for kw in UNSAFE_KEYWORDS)
