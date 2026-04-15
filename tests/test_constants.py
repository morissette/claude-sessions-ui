"""Tests for backend.constants — MODEL_PRICING and time-range config."""

import backend

# ─── Cost calculation ─────────────────────────────────────────────────────────

class TestModelPricing:
    def test_known_model_haiku(self):
        pricing = backend.MODEL_PRICING["claude-haiku-4-5"]
        assert pricing["input"] == 0.80
        assert pricing["output"] == 4.00
        assert pricing["cache_write"] == 1.00
        assert pricing["cache_read"] == 0.08

    def test_known_model_sonnet(self):
        pricing = backend.MODEL_PRICING["claude-sonnet-4-6"]
        assert pricing["input"] == 3.00
        assert pricing["output"] == 15.00

    def test_default_pricing_exists(self):
        assert "default" in backend.MODEL_PRICING

    def test_all_models_have_required_keys(self):
        required = {"input", "output", "cache_write", "cache_read"}
        for model, pricing in backend.MODEL_PRICING.items():
            assert required <= set(pricing.keys()), f"{model} missing pricing keys"
