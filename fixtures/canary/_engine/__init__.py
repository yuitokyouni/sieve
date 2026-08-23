"""Minimal, dependency-free engines and helpers for the canary fixtures.

Nothing in here imports sieve, numpy or scipy. That is deliberate: a canary
that needs the numerical stack cannot be used to check the numerical stack,
and a canary that takes seconds to install cannot be run on every push.
"""
