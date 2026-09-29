"""Bundled offline providers.

Everything here exists so the brain runs end to end before any teammate's real adapter lands.
They are real implementations of the Protocols in :mod:`brain.contracts`, not test doubles:
the loop cannot tell the difference, which is what makes the swap safe.
"""
