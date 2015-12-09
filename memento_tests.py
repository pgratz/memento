import memento
import unittest
import logging
import logging.handlers
import configparser

class MementoTestCase(unittest.TestCase):

    def setUp(self):
        self.fixture = TestFixture(open('test-config.ini'))
        memento.LOGGER = logging.getLogger()
        memento.app.config['TESTING'] = True
        self.app = memento.app.test_client()

    def test_original_resource(self):
        r = self.app.get(self.fixture.original_timegate, headers={'Accept': 'application/rdf+xml'})
        self.assertNotIn('Memento-Datetime',r.headers)
        self.assertEqual(303,r.status_code)
        self.assertIn(self.fixture.original_timegate+'>; rel="original timegate"',r.headers['Link']) # thelen
        self.assertIn(self.fixture.original_timemap+'>; rel="timemap"',r.headers['Link']) # thelen
        self.assertIn('Location',r.headers)
        self.assertNotIn(r.location,self.fixture.mementos)
        self.assertNotIn(r.location, self.fixture.intermediate_resources)
        self.assertNotIn(r.location, self.fixture.intermediate_timegates)
        self.assertNotIn(r.location, self.fixture.intermediate_timemaps)
        self.assertIn('accept-datetime',r.vary) # thelen

    def test_original_timegate(self):
        r = self.app.get(self.fixture.original_timegate, headers={'Accept': 'application/rdf+xml', 'Accept-Datetime':'Sat, 10 Nov 2012 12:00:0 GMT'})
        self.assertEqual(302,r.status_code)
        self.assertIn(self.fixture.original_timegate+'>; rel="original timegate"',r.headers['Link'])
        self.assertIn(self.fixture.original_timemap+'>; rel="timemap"',r.headers['Link'])
        self.assertIn('Location',r.headers)
        assert r.location in self.fixture.intermediate_resources or self.fixture.intermediate_timegates
        self.assertIn('accept-datetime',r.vary)
        self.assertNotIn('Memento-Datetime',r.headers)

    def test_original_timemap(self):
        r = self.app.get(self.fixture.original_timemap)
        self.assertEqual(200,r.status_code)
        self.assertIn('application/link-format', r.content_type)
        self.assertNotIn('accept-datetime',r.vary)
        self.assertNotIn('Memento-Datetime',r.headers)
        self.assertIn(self.fixture.original_timegate+'>;rel="original timegate"', str(r.data))
        self.assertIn(self.fixture.original_timemap+'>;rel="self";type="application/link-format"', str(r.data))
        # self.assertGreaterEqual(str(r.data).count('rel="memento"'), 0) thelen (compare to number of mementos defined in config?)
        # self.assertGreaterEqual(str(r.data).count('rel="timemap"'), 0) thelen (compare to number of mementos defined in config?)

    def test_intermediate_timegate(self):
        for i in self.fixture.intermediate_timegates:
            r = self.app.get(i, headers={'Accept': 'application/rdf+xml', 'Accept-Datetime':'Sat, 10 Nov 2012 12:00:0 GMT'})
            self.assertEqual(302,r.status_code)
            assert r.location in self.fixture.intermediate_resources or self.fixture.intermediate_timegates
            self.assertIn(self.fixture.original_timegate+'>; rel="original timegate"', r.headers['Link'])
            self.assertIn(self.fixture.original_timemap+'>; rel="timemap"', r.headers['Link'])
            self.assertIn('accept-datetime',r.vary) # thelen
            self.assertNotIn('Memento-Datetime',r.headers)

    def test_intermediate_timemap(self):
        for i in self.fixture.intermediate_timemaps:
            r = self.app.get(i)
            self.assertEqual(200,r.status_code)
            self.assertIn('application/link-format', r.content_type)
            self.assertNotIn('accept-datetime',r.vary)
            self.assertNotIn('Memento-Datetime',r.headers)
            self.assertIn(self.fixture.original_timegate+'>;rel="original timegate"', str(r.data))
            self.assertIn(i+'>;rel="self";type="application/link-format"', str(r.data))
            # self.assertGreaterEqual(str(r.data).count('rel="memento"'), 0) thelen (compare to number of mementos defined in config?)
            # self.assertGreaterEqual(str(r.data).count('rel="timemap"'), 0) thelen (compare to number of mementos defined in config?)

    def test_memento(self):
        for i in self.fixture.mementos:
            r = self.app.get(i)
            self.assertEqual(200,r.status_code)
            self.assertIn('application/rdf+xml',r.content_type)
            self.assertIn('Memento-Datetime', r.headers)
            self.assertNotIn('accept-datetime', r.vary)
            self.assertIn(self.fixture.original_timegate+'>; rel="original timegate"',r.headers['Link'])
            self.assertIn(self.fixture.original_timemap+'>; rel="timemap"', r.headers['Link'])
            self.assertIn(self.fixture.first_memento+'>; rel="memento first"', r.headers['Link'])
            self.assertIn(self.fixture.last_memento+'>; rel="memento last"', r.headers['Link'])

    def test_intermediate_resource(self):
        for i in self.fixture.intermediate_resources:
            r = self.app.get(i,headers={'Accept': 'application/rdf+xml', 'Accept-Datetime':'Sat, 10 Nov 2012 12:00:0 GMT'})
            self.assertEqual(303,r.status_code)
            assert r.location not in self.fixture.intermediate_resources or self.fixture.intermediate_timegates # thelen
            self.assertIn(r.location, self.fixture.mementos)
            self.assertNotIn('Memento-Datetime', r.headers)
            self.assertIn(self.fixture.original_timegate+'>; rel="original timegate"',r.headers['Link'])
            self.assertIn(self.fixture.original_timemap+'>; rel="timemap"', r.headers['Link'])

if __name__ == '__main__':
   unittest.main()


class TestFixture:

    def __init__(self, file):
        config_parser = configparser.ConfigParser()
        config_parser.read_file(file)
        self.original_timegate = config_parser.get('resources','original_timegate')
        self.original_timemap = config_parser.get('resources','original_timemap')
        self.intermediate_timemaps =  config_parser.get('resources','intermediate_timemaps').splitlines()
        self.intermediate_timegates = config_parser.get('resources','intermediate_timegates').splitlines()
        self.intermediate_resources = config_parser.get('resources','intermediate_resources').splitlines()
        self.mementos = config_parser.get('resources','mementos').splitlines()
        self.first_memento = config_parser.get('resources','first_memento')
        self.last_memento = config_parser.get('resources','last_memento')
