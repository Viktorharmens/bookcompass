"""Tests voor de controle-logica van groq_recommender (zonder netwerk). Draaien: python -m unittest discover -s tests"""

import os
import sys
import asyncio
import unittest
from unittest import mock

os.environ.setdefault('GROQ_API_KEY', 'test')  # AsyncGroq wil een sleutel; het model wordt hier gemockt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import groq_recommender  # noqa: E402
from groq_recommender import author_matches, filter_candidates, parse_books, title_matches  # noqa: E402


class TitleMatchTest(unittest.TestCase):
    def test_exact_and_accents(self):
        self.assertTrue(title_matches('De avonden', 'De Avonden'))
        self.assertTrue(title_matches('Één dag', 'Een dag'))

    def test_subtitle_and_prefix(self):
        self.assertTrue(title_matches('Tirza', 'Tirza: roman'))
        self.assertTrue(title_matches('Lijmen', 'Lijmen; Het been'))

    def test_different_titles(self):
        self.assertFalse(title_matches('De onzichtbare man', 'De man zonder verleden'))
        self.assertFalse(title_matches('Tirza', 'Tirzah'))


class AuthorMatchTest(unittest.TestCase):
    def test_surname(self):
        self.assertTrue(author_matches('Gerard Reve', ['Gerard Kornelis van het Reve']))
        self.assertTrue(author_matches('Reve, Gerard', ['Gerard Reve']))

    def test_wrong_author(self):
        # Het voorbeeld uit de praktijk: "De avonden" toegeschreven aan Marcel Möring.
        self.assertFalse(author_matches('Marcel Möring', ['Gerard Reve']))
        self.assertFalse(author_matches('Graham Graham', ['Graham Greene']))


class FilterCandidatesTest(unittest.TestCase):
    def test_filters(self):
        books = [
            {'title': 'Tirza', 'author': 'Arnon Grunberg'},
            {'title': 'Blauwe maandagen', 'author': 'Arnon Grunberg'},
            {'title': 'De avonden', 'author': 'Gerard Reve'},
            {'title': 'De Avonden', 'author': 'Gerard  Reve'},
            {'title': 'Het diner', 'author': 'Herman Koch'},
            {'title': 'Stoner', 'author': 'John Williams'},
            {'title': 'Butcher\'s Crossing', 'author': 'John Williams'},
            {'title': '', 'author': 'X'},
            {'title': 5, 'author': 'Y'},
        ]
        seen = set()
        out = filter_candidates(books, 'Tirza', 'Arnon Grunberg', ['Het diner'], seen)
        self.assertEqual([b['title'] for b in out], ['De avonden', 'Stoner'])
        # Een tweede ronde krijgt geen dubbelen.
        again = filter_candidates([{'title': 'Stoner', 'author': 'John Williams'}], 'Tirza', 'Arnon Grunberg', [], seen)
        self.assertEqual(again, [])


class ParseBooksTest(unittest.TestCase):
    def test_valid_array(self):
        self.assertEqual(len(parse_books('tekst [{"title": "A", "author": "B"}] meer')), 1)

    def test_broken_array_keeps_good_objects(self):
        raw = '[{"title": "A", "author": "B"}, {"title": "C", "author": }, {"title": "D", "author": "E"}'
        self.assertEqual([b['title'] for b in parse_books(raw)], ['A', 'D'])


class RecommendFlowTest(unittest.TestCase):
    """De hele flow met een nep-model en nep-bronnen: verzonnen boeken vallen weg en een tweede ronde vult aan."""

    def run_recommend(self, rounds, real, **kwargs):
        prompts = []

        async def fake_model(_client, prompt):
            prompts.append(prompt)
            return rounds[len(prompts) - 1] if len(prompts) <= len(rounds) else []

        async def fake_verify(item, _client, _sem):
            if item['title'] not in real:
                return {}
            return {'source': 'openlibrary', 'ol_key': '/works/' + item['title'], 'year': 2000}

        with mock.patch.object(groq_recommender, '_ask_model', fake_model), \
                mock.patch.object(groq_recommender, '_verify', fake_verify):
            recs = asyncio.run(groq_recommender.recommend('Tirza', 'Arnon Grunberg', '', [], k=3, **kwargs))
        return recs, prompts

    def test_refill_after_rejections(self):
        first = [{'title': t, 'author': f'Auteur {t}'} for t in ['A', 'Verzonnen1', 'B', 'Verzonnen2']]
        second = [{'title': t, 'author': f'Auteur {t}'} for t in ['A', 'C', 'D']]
        recs, prompts = self.run_recommend([first, second], real={'A', 'B', 'C', 'D'}, exclude=['Oud boek'])
        self.assertEqual([r.title for r in recs], ['A', 'B', 'C'])
        self.assertTrue(all(r.ol_key for r in recs))
        self.assertEqual(len(prompts), 2)
        # De tweede ronde krijgt de exclude-lijst en alles wat al genoemd is mee.
        for title in ('Oud boek', 'A', 'Verzonnen1', 'B'):
            self.assertIn(f'"{title}"', prompts[1])

    def test_no_refill_when_enough(self):
        first = [{'title': t, 'author': f'Auteur {t}'} for t in ['A', 'B', 'C', 'D']]
        recs, prompts = self.run_recommend([first], real={'A', 'B', 'C', 'D'})
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(prompts), 1)


if __name__ == '__main__':
    unittest.main()
