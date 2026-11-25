"""Model providers beyond Bedrock (MVP-2.9.0 N35, owner 2026-11-25).

A model is referenced as `<provider>::<model id>` (`refs`); a value without `::` is a Bedrock model id, so every
existing setting keeps its meaning. Providers live in the database (`models`, `registry`); `factory.build_model` is the
one place a Strands model is built and `direct.complete_text` the single-turn call for the non-Bedrock protocols.
"""
