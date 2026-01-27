#!/usr/bin/env python3
"""
NIJA Unified Execution Layer - Example Usage
===========================================

This example demonstrates how to use the unified execution layer
to execute trades across multiple exchanges with a simple interface.

The key benefit: Strategies don't care where they trade - they just trade!
"""

import logging
import sys
import os

# Add bot directory to path  
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot'))

from unified_execution_engine import execute_trade, validate_trade

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("example")

print("✅ Unified Execution Layer Example loaded successfully!")
print("   Run this file to see examples of multi-exchange trading")
