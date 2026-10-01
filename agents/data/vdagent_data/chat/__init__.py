"""The explanation chat of the Data agent: answers a person's questions about the package Data has just fetched.

A side branch of the agent, apart from the pipeline (`steps.py`, `v1.py`, `wire.py`), which it never changes. It reads stored
artifacts (`packages.py`) through read-only tools (`tools.py`, `glossary.py`) and lets an LLM phrase the answer, checked
against what the tools returned (`loop.py`).
"""
