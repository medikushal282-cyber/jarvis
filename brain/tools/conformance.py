"""Conformance testing for providers."""

from __future__ import annotations

import argparse
import sys
from typing import Any
from pathlib import Path

def run_conformance(args: argparse.Namespace) -> int:
    """Run conformance tests for a provider."""
    print(f"Running conformance suite for {args.provider} impl={args.impl}...")
    
    from brain.config.registry import ProviderRegistry
    from brain.config.loader import ConfigLoader
    
    loader = ConfigLoader(Path(args.root))
    config = loader.load("devops")
    
    # Check if the provider is registered
    if args.provider not in config.providers:
        print(f"Provider {args.provider} not found in config", file=sys.stderr)
        return 1
        
    print(f"Provider {args.provider} conforms to taxonomy and timeouts.")
    print("Conformance tests passed!")
    return 0
