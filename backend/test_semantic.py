"""Local contract tests; no OpenRouter credential or network request is used."""

import json
import os
import unittest
from unittest.mock import patch

from . import semantic


def _api_result(mode: str, arguments: dict) -> dict:
    return {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"tool_calls": [{
                "type": "function",
                "function": {
                    "name": "plan_hotel_search" if mode == "hotels" else "plan_tour_search",
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }]},
        }],
    }


class _Response:
    content = b"{}"

    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


class _Client:
    calls: list[tuple[str, dict, dict]] = []
    payload: dict = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url: str, *, headers: dict, json: dict) -> _Response:
        self.calls.append((url, headers, json))
        return _Response(self.payload)


class SemanticTests(unittest.TestCase):
    def setUp(self) -> None:
        semantic._SUCCESS_CACHE.clear()
        _Client.calls.clear()

    def test_hotel_plan_normalizes_numbered_name_and_union(self) -> None:
        plan = semantic._validated_plan({
            "city_ids": ["kish", "rasht"],
            "destination_theme": "coastal",
            "hotel_name_terms": ["الماس ۲"],
            "max_price_toman": 6_000_000,
            "sort": "price",
        }, "hotels", "هتل الماس ۲ در کیش یا رشت زیر ۶ میلیون")
        self.assertEqual(plan["hotel_name_terms"], ["الماس", "2"])
        self.assertEqual(plan["city_ids"], ["kish", "rasht"])
        self.assertEqual(semantic._validated_plan({"has_tours": True}, "hotels", "هتل با تور"),
                         {"has_tours": True})
        with self.assertRaises(semantic.InvalidPlan):
            semantic._validated_plan({"has_tours": "true"}, "hotels", "هتل با تور")

    def test_rejects_unknown_fields_and_unstated_dates(self) -> None:
        with self.assertRaises(semantic.InvalidPlan):
            semantic._validated_plan({"sql": "DELETE FROM tours"}, "tours", "مشهد")
        with self.assertRaises(semantic.InvalidPlan):
            semantic._validated_plan({"destination_city": "unknown"}, "tours", "مشهد")
        with self.assertRaises(semantic.InvalidPlan):
            semantic._validated_plan({"max_price_toman": True}, "tours", "زیر ۵ میلیون")
        with self.assertRaises(semantic.InvalidPlan):
            semantic._validated_plan({"departure_date": "1405/08/20"}, "tours", "فردا")

    def test_forced_function_and_success_cache(self) -> None:
        _Client.payload = _api_result("tours", {
            "departure_city": "tehran", "destination_city": "kish",
            "hotel_name": "هتل پانوراما", "service": "صبحانه",
            "transport": "flight", "max_price_toman": 8_000_000,
        })
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only", "OPENROUTER_MODEL": "openrouter/free"}), \
             patch.object(semantic.httpx, "Client", _Client):
            first = semantic.plan_query("تور پروازی تهران به کیش هتل پانوراما با صبحانه زیر ۸ میلیون", "tours")
            second = semantic.plan_query("تور پروازی تهران به کیش هتل پانوراما با صبحانه زیر ۸ میلیون", "tours")
        self.assertEqual(first, second)
        self.assertEqual(first[1], "openrouter")
        self.assertEqual(len(_Client.calls), 1)
        url, headers, body = _Client.calls[0]
        self.assertEqual(url, semantic.OPENROUTER_URL)
        self.assertEqual(headers["Authorization"], "Bearer test-only")
        self.assertEqual(body["tool_choice"]["function"]["name"], "plan_tour_search")
        self.assertFalse(body["parallel_tool_calls"])

    def test_missing_key_and_wrong_function_fall_back(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertEqual(semantic.plan_query("هتل کیش", "hotels"), (None, "fallback"))
        _Client.payload = _api_result("tours", {"destination_city": "kish"})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}), \
             patch.object(semantic.httpx, "Client", _Client):
            self.assertEqual(semantic.plan_query("هتل کیش", "hotels"), (None, "fallback"))


if __name__ == "__main__":
    unittest.main()
