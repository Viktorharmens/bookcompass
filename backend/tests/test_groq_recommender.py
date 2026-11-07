"""Tests voor de controle-logica van groq_recommender (zonder netwerk). Draaien: python -m unittest discover -s tests"""

import os
import sys
import asyncio
import unittest
from unittest import mock

os.environ.setdefault('GROQ_API_KEY', 'test')  # AsyncGroq wil een sleutel; het model wordt hier gemockt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import groq_recommender  # noqa: E402
from groq_recommender import (  # noqa: E402
    author_matches, display_title_author, filter_candidates, parse_books, select, title_matches,
)


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

    def test_dutch_title_only_when_confirmed(self):
        first = [
            {'title': 'A', 'author': 'Auteur A', 'year': 2010, 'lang': 'EN', 'dutch_title': 'Nl A'},
            {'title': 'B', 'author': 'Auteur B', 'year': 2011, 'lang': 'en', 'dutch_title': 'Nl B'},
            {'title': 'C', 'author': 'Auteur C', 'year': 2012, 'lang': 'nl'},
        ]

        async def fake_model(_client, _prompt):
            return first

        async def fake_verify(item, _client, _sem):
            return {'source': 'openlibrary', 'ol_key': '/works/' + item['title'], 'dutch_confirmed': item['title'] == 'A'}

        with mock.patch.object(groq_recommender, '_ask_model', fake_model), \
                mock.patch.object(groq_recommender, '_verify', fake_verify):
            recs = asyncio.run(groq_recommender.recommend('Tirza', 'Arnon Grunberg', '', [], k=3))
        self.assertEqual([(r.dutch_title, r.original_language) for r in recs], [('Nl A', 'en'), (None, 'en'), (None, 'nl')])

    def test_no_refill_when_enough(self):
        first = [{'title': t, 'author': f'Auteur {t}'} for t in ['A', 'B', 'C', 'D']]
        recs, prompts = self.run_recommend([first], real={'A', 'B', 'C', 'D'})
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(prompts), 1)


class FilterDutchTitleTest(unittest.TestCase):
    def test_blocked_by_dutch_title(self):
        books = [{'title': 'The Dinner', 'author': 'Someone Else', 'dutch_title': 'Het etentje'}]
        self.assertEqual(filter_candidates(books, 'Tirza', 'Arnon Grunberg', ['Het etentje'], set()), [])


def _pair(title, year, lang='en'):
    return ({'title': title, 'author': 'X ' + title, 'year': year, 'lang': lang}, {'ol_key': '/works/' + title})


class SelectTest(unittest.TestCase):
    def test_at_most_two_classics(self):
        found = [_pair('Oud1', 1950), _pair('Oud2', 1960), _pair('Oud3', 1970), _pair('Nieuw1', 2015), _pair('Nieuw2', 2020)]
        self.assertEqual([p[0]['title'] for p in select(found, 4, 'en')], ['Oud1', 'Oud2', 'Nieuw1', 'Nieuw2'])

    def test_fill_with_classics_rather_than_empty(self):
        found = [_pair('Oud1', 1950), _pair('Oud2', 1960), _pair('Oud3', 1970), _pair('Nieuw1', 2015)]
        self.assertEqual(len(select(found, 4, 'en')), 4)

    def test_dutch_books_pulled_up(self):
        found = [_pair(f'En{i}', 2010) for i in range(5)] + [_pair('Nl1', 2012, 'nl'), _pair('Nl2', 2014, 'NL')]
        titles = [p[0]['title'] for p in select(found, 5, 'nl')]
        self.assertEqual(titles, ['En0', 'En1', 'En2', 'Nl1', 'Nl2'])
        # Engelstalige bezoeker: gewoon de volgorde van het model.
        self.assertEqual([p[0]['title'] for p in select(found, 5, 'en')], [f'En{i}' for i in range(5)])


class DisplayTitleAuthorTest(unittest.TestCase):
    def test_source_author_and_subtitle(self):
        item = {'title': 'Stoner: A Novel', 'author': 'John Williams'}
        self.assertEqual(display_title_author(item, {'title': 'Stoner', 'author': 'John Williams'}),
                         ('Stoner', 'John Williams'))
        # Spelling met accenten van de bron, maar geen langere naamsvorm.
        self.assertEqual(display_title_author({'title': 'Lullaby', 'author': 'Leila Slimani'},
                                              {'title': 'Lullaby', 'author': 'Leïla Slimani'})[1], 'Leïla Slimani')
        self.assertEqual(display_title_author({'title': 'De avonden', 'author': 'Gerard Reve'},
                                              {'title': 'De avonden', 'author': 'Gerard Kornelis van het Reve'})[1],
                         'Gerard Reve')

    def test_keep_model_author_for_non_latin_or_several(self):
        self.assertEqual(display_title_author({'title': 'A', 'author': 'Haruki Murakami'}, {'title': 'A', 'author': '村上 春樹'})[1],
                         'Haruki Murakami')
        self.assertEqual(display_title_author({'title': 'A', 'author': 'Nicci French & Sean French'},
                                              {'title': 'A', 'author': 'Nicci French'})[1],
                         'Nicci French & Sean French')


class VerifyTest(unittest.TestCase):
    """_verify probeert eerst de Nederlandse titel, dan de originele, in Open Library en daarna Google Books."""

    def run_verify(self, item, ol_hits, gb_hits):
        calls = []

        async def fake_ol(title, author, _client, also_title=''):
            calls.append(('ol', title))
            return {'source': 'openlibrary', 'ol_key': '/works/1'} if title in ol_hits else {}

        async def fake_gb(title, author, _client):
            calls.append(('gb', title))
            return {'source': 'google_books', 'source_id': 'gb1'} if title in gb_hits else {}

        with mock.patch.object(groq_recommender, '_ol_lookup', fake_ol), \
                mock.patch.object(groq_recommender, '_gb_lookup', fake_gb):
            meta = asyncio.run(groq_recommender._verify(item, None, asyncio.Semaphore(1)))
        return meta, calls

    def test_dutch_title_confirmed(self):
        meta, calls = self.run_verify({'title': 'The Dinner', 'author': 'A B', 'dutch_title': 'Het etentje'},
                                      ol_hits={'Het etentje', 'The Dinner'}, gb_hits=set())
        self.assertTrue(meta['dutch_confirmed'])
        self.assertEqual(calls, [('ol', 'Het etentje')])

    def test_original_title_only(self):
        meta, calls = self.run_verify({'title': 'The Dinner', 'author': 'A B', 'dutch_title': 'Verzonnen'},
                                      ol_hits={'The Dinner'}, gb_hits=set())
        self.assertFalse(meta['dutch_confirmed'])
        self.assertEqual(calls, [('ol', 'Verzonnen'), ('ol', 'The Dinner')])

    def test_google_books_fallback_and_invented(self):
        meta, _ = self.run_verify({'title': 'Boek', 'author': 'A B', 'dutch_title': None}, set(), {'Boek'})
        self.assertEqual(meta['source'], 'google_books')
        meta, calls = self.run_verify({'title': 'Verzonnen', 'author': 'A B'}, set(), set())
        self.assertEqual(meta, {})
        self.assertEqual(calls, [('ol', 'Verzonnen'), ('gb', 'Verzonnen')])


if __name__ == '__main__':
    unittest.main()
