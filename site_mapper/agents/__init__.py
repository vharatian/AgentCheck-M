# Agent Swarm for Prompt Generation
"""
This module contains the 4-agent swarm for generating diverse, grounded prompts.

Agents:
- flow_discovery: Discovers user flows from site map
- diversity: Generates prompt variations
- dedupe: Removes duplicate prompts
- judge: Scores and filters prompts
"""

# Import agents as they are implemented
from .flow_discovery import FlowDiscoveryAgent, UserFlow, DiscoveryResult, FlowType

__all__ = [
    "FlowDiscoveryAgent", 
    "UserFlow", 
    "DiscoveryResult", 
    "FlowType"
]

# Swarm orchestrator will be added after all agents are implemented
# from .swarm import PromptSwarm
