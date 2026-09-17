"""The ranking must be driven by evidence, and must not recommend something forbidden."""

import unittest

from nmrx.reports.ranking import rank_next_connectors, score_source
from nmrx.sources.policy import load_policy
from nmrx.sources.registry import load_registry


class TestRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()
        cls.policy = load_policy()
        cls.ranked = rank_next_connectors(cls.registry, policy=cls.policy)

    def test_prohibited_sources_are_never_recommended(self):
        ids = [r.source_id for r in self.ranked]
        self.assertNotIn("sdbs", ids)

    def test_already_granted_sources_are_excluded(self):
        ids = [r.source_id for r in self.ranked]
        for source_id in ("pubchem", "nmrshiftdb2", "rcsb", "bindingdb"):
            with self.subTest(source=source_id):
                self.assertNotIn(source_id, ids)

    def test_the_expansion_three_lead_the_ranking(self):
        """The map's recommended next NMR expansion should fall out of the scoring."""
        top3 = {r.source_id for r in self.ranked[:3]}
        self.assertEqual(top3, {"nmrxiv", "chemotion", "bmrb"})

    def test_results_are_sorted_by_score(self):
        scores = [r.score for r in self.ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_every_result_shows_its_components(self):
        for r in self.ranked:
            with self.subTest(source=r.source_id):
                self.assertEqual(
                    set(r.components),
                    {"measured_nmr", "assignments", "conditions", "rights",
                     "retrievability", "access_simplicity"},
                )

    def test_limit_is_honoured(self):
        self.assertEqual(len(rank_next_connectors(self.registry, policy=self.policy, limit=2)), 2)


class TestCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_unverified_rights_are_surfaced_as_a_cost(self):
        ranked = score_source(self.registry["bmrb"])
        self.assertTrue(any("CAL-008" in c for c in ranked.costs),
                        "an unread licence must be shown as a cost, not hidden in a score")

    def test_a_licensed_source_is_capped_and_labelled(self):
        ranked = score_source(self.registry["drugbank"])
        self.assertLessEqual(ranked.score, 2.0)
        self.assertTrue(any("licence" in c for c in ranked.costs))

    def test_a_prohibited_source_scores_zero(self):
        self.assertEqual(score_source(self.registry["sdbs"]).score, 0.0)

    def test_granted_hosts_are_not_listed_as_hosts_to_open(self):
        policy = load_policy()
        ranked = score_source(self.registry["chembl"], policy=policy)
        self.assertNotIn("www.ebi.ac.uk", ranked.hosts_to_open)


class TestScoringIsConservative(unittest.TestCase):
    def test_unknown_scores_below_partial(self):
        from nmrx.reports.ranking import VERDICT_SCORE
        self.assertLess(VERDICT_SCORE["unknown"], VERDICT_SCORE["partial"])

    def test_an_unestablished_licence_scores_below_a_documented_one(self):
        from nmrx.reports.ranking import RIGHTS_SCORE
        self.assertLess(RIGHTS_SCORE["unverified"], RIGHTS_SCORE["open_documented"])
        self.assertEqual(RIGHTS_SCORE["licensed_required"], 0.0)

    def test_there_is_no_verified_rights_score(self):
        """Nothing has been verified against a live service, so the word must not appear."""
        from nmrx.reports.ranking import RIGHTS_SCORE
        self.assertNotIn("open_verified", RIGHTS_SCORE)


if __name__ == "__main__":
    unittest.main()
