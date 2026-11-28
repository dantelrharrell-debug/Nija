"""Offline checks of the staged IONOS crawl configuration (not access control)."""
from pathlib import Path
import unittest
from urllib.robotparser import RobotFileParser


class IonosRobotsPolicyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "ops/website/ionos/robots.txt"
        self.policy = RobotFileParser()
        self.policy.parse(path.read_text(encoding="utf-8").splitlines())

    def test_public_routes_remain_crawlable(self):
        routes = (
            "/",
            "/free",
            "/trading-foundations",
            "/trading-iq-challenge",
            "/founding-waitlist",
            "/privacy-policy",
            "/account-deletion",
            "/academy",
            "/academy/courses",
            "/merch",
            "/support",
            "/pricing",
        )
        for agent in ("Googlebot", "GPTBot", "OAI-SearchBot", "ClaudeBot",
                      "PerplexityBot"):
            for route in routes:
                with self.subTest(agent=agent, route=route):
                    self.assertTrue(self.policy.can_fetch(agent, "https://nijaaitrading.com" + route))

    def test_restricted_prefixes_are_disallowed(self):
        routes = (
            "/dashboard",
            "/admin",
            "/founder-dashboard",
            "/affiliate-dashboard",
            "/course-access",
            "/course-thank-you",
            "/automation-setup",
            "/contacts",
            "/revenue-dashboard",
            "/outreach-center",
            "/calling-system",
            "/beta-success",
            "/beta-thank-you",
            "/sponsor-thank-you",
            "/partner-thank-you",
            "/affiliate-creator-thank-you",
            "/academy/dashboard",
            "/academy/parents",
            "/academy/educators",
            "/gunit",
            "/enroll",
            "/game",
        )
        for agent in ("Googlebot", "GPTBot", "OAI-SearchBot", "ClaudeBot",
                      "PerplexityBot"):
            for route in routes:
                for suffix in ("", "/example"):
                    with self.subTest(agent=agent, route=route, suffix=suffix):
                        self.assertFalse(self.policy.can_fetch(
                            agent, "https://nijaaitrading.com" + route + suffix))

    def test_sitemap_location_is_preserved(self):
        self.assertEqual(self.policy.site_maps(), ["https://nijaaitrading.com/sitemap.xml"])
