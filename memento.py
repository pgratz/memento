# Authors: Sebastian Thelen, Patrick Gratz
# Description: The following code represents a prototypical implementation of the Memento framework (RFC 7089). For further information concerning Memento we refer to http://www.mementoweb.org/.
# Prerequisites: Python 3.x, Flask microframework for Python
# (http://flask.pocoo.org/), Virtuoso 7 or a triple store with an
# equivalent SPARQL endpoint

from flask import Flask
from flask import request
from flask import redirect
from flask import make_response
from pytz import timezone
import time
import requests
import json
import logging
import logging.handlers
import email.utils as eut
import datetime
import pytz

# suppress logging messages from requests lib
requests_log = logging.getLogger("requests")
requests_log.setLevel(logging.ERROR)

# global variable stores address of host and sparql-endpoint

local_host = 'http://localhost:5000'
sparql_endpoint = 'http://abel:8890/sparql'
app = Flask(__name__)

PREDECESSOR_RELATION = 'http://publications.europa.eu/ontology/cdm#is_predecessor'
# namespace of cellar environment, e.g. dz, tz, or prod
CELLAR_BASE = "http://publications.europa.eu"

# compute original resource (URI-G) in a hierarchy
URI_R_TEMPLATE = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?predecessor where { '
    ' <%(uri)s> ^owl:sameAs? ?s.'
    '?predecessor ^cdm:work_is_member_of_complex_work* ?s; '
    'cdm:datetime_negotiation ?o.'
    'filter not exists{?predecessor cdm:work_is_member_of_complex_work ?anotherWork.}} '
)

# compute location field of next redirect based on
# current uri and accept-datetime parameter
LOCATION_TEMPLATE_NEAREST_IN_PAST = (
    "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> "
    "SELECT ?successor ?diff_date WHERE {"
    "?successor ?datetime_property ?date."
    "BIND(bif:datediff('minute', ?date, xsd:dateTime('%(accept_datetime)s')) as ?diff_date)"
    "FILTER (?diff_date >= 0) {"
    "SELECT distinct ?successor ?datetime_property "
    "WHERE {"
    "?s owl:sameAs? <%(uri)s>."
	"?s cdm:datetime_negotiation ?datetime_property."
    "?successor cdm:work_is_member_of_complex_work ?s."
	"}}"
	"}"
	"ORDER BY ASC(?diff_date)"
	"LIMIT 1"
)

# compute location information of next redirect based on
# current uri and accept-datetime parameter
LOCATION_TEMPLATE_NEAREST_IN_FUTURE = (
    "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> "
    "SELECT ?successor ?diff_date WHERE {"
    "?successor ?datetime_property ?date."
    "BIND(bif:datediff('minute', ?date, xsd:dateTime('%(accept_datetime)s')) as ?diff_date)"
    "FILTER (?diff_date <= 0) {"
    "SELECT distinct ?successor ?datetime_property "
    "WHERE {"
    "?s owl:sameAs? <%(uri)s>."
	"?s cdm:datetime_negotiation ?datetime_property."
    "?successor cdm:work_is_member_of_complex_work ?s."
	"}}"
	"}"
	"ORDER BY DESC(?diff_date)"
	"LIMIT 1"
)

# perform sparql describe query for given uri
DESCRIBE_TEMPLATE = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> '
    'DESCRIBE <%(uri)s> '
)

# test whether given work is instance of cdm:evolutive_work
EVOLUTIVE_WORK_TEMPLATE = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> '
    'SELECT ?p where { <%(uri)s> ^owl:sameAs? ?s. ?s a cdm:evolutive_work; ?p ?o.}'
)

# return memento datetime of given resource
MEMENTO_DATETIME_TEMPLATE = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>'
    'select ?date '
    'where '
    '{<%(uri)s> ^owl:sameAs? ?s.'
    '?s ?p ?date;cdm:work_is_member_of_complex_work ?tg.'
    '?tg cdm:datetime_negotiation ?p.}'
)

# return related complex works
RELATED_EVOLUTIVE_WORKS = (
    'prefix cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?evolutive_work where {'
    ' ?s owl:sameAs? <%(uri)s>.'
    '?evolutive_work cdm:work_is_member_of_complex_work ?s; a cdm:evolutive_work. }'
)
# return related mementos together with their memento-datetime
RELATED_MEMENTOS = (
    'prefix cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?memento ?date where {'
    '?s owl:sameAs? <%(uri)s>; cdm:datetime_negotiation ?p.'
    '?memento cdm:work_is_member_of_complex_work ?s; ?p ?date.'
    'filter not exists { ?member cdm:work_is_member_of_complex_work ?memento.} }'
)

# return timeamp related information (startdate, enddate and type of date)
TIMEMAPINFO = (
    'prefix cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select (min(?o) as ?startdate) (max(?o) as ?enddate) (?p as ?typeofdate) where {'
    '<%(uri)s> ^owl:sameAs?/cdm:datetime_negotiation ?p;  '
    '^owl:sameAs?/^cdm:work_is_member_of_complex_work ?member. '
    '?member ?p ?o.}'
)

FIRST_MEMENTO_TEMPLATE = (
    'prefix cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?individual_work ?date where { '
    '<%(uri)s> ^owl:sameAs?/^cdm:work_is_member_of_complex_work+ ?individual_work. '
    '?individual_work cdm:work_is_member_of_complex_work ?predecessor; ?p ?date. '
    '?predecessor cdm:datetime_negotiation ?p. '
    'FILTER NOT EXISTS {?individual_work a cdm:evolutive_work.} '
    '} ORDER BY ASC(?date) '
    'LIMIT 1 '
)

LAST_MEMENTO_TEMPLATE = (
    'prefix cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?individual_work ?date where { '
    '<%(uri)s> ^owl:sameAs?/^cdm:work_is_member_of_complex_work+ ?individual_work. '
    '?individual_work cdm:work_is_member_of_complex_work ?predecessor; ?p ?date. '
    '?predecessor cdm:datetime_negotiation ?p. '
    'FILTER NOT EXISTS {?individual_work a cdm:evolutive_work.} '
    '} ORDER BY DESC(?date) '
    'LIMIT 1 '
)

RELATED_PREDECESSORS = (
    'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> '
    'select distinct ?predecessor (group_concat(?lg;separator=", ") as ?languages) where {'
    '<%(uri)s> cdm:work_is_logical_successor_of_work+ ?predecessor .'
    '?predecessor ^cdm:expression_belongs_to_work/cdm:expression_uses_language ?lang. ?lang dc:identifier ?lg.'
    'filter not exists {?predecessor ^cdm:work_is_logical_successor_of_work+/^cdm:expression_belongs_to_work/cdm:expression_uses_language ?lang.}'
    '}'
)


def sparqlQuery(query, format="application/json"):
    """perform sparql query and return the corresponding bindings"""
    payload = {
        "default-graph-uri": "",
        "query": query,
        "debug": "on",
        "timeout": "",
        "format": format
    }
    resp = requests.get(sparql_endpoint, params=payload)
    if format == "application/json":
        json_results = json.loads(resp.text)
        return json_results['results']['bindings']
    return resp.text

def get_URI_R(uri):
    """retrieves URI of the related original resource"""
    query = URI_R_TEMPLATE % {'uri': uri}
    sparql_results = sparqlQuery(query)
    # global uri_r
    if not sparql_results:
        return None
    uri_r = sparql_results[0]['predecessor']['value']
    return uri_r

@app.route('/hello')
def processRootRequest(id=None):
    return "hello"

@app.route('/memento/<id>')
def processMementoRequest(id=None):
    """Process memento service request (non-information resources)

      For simplicity prototype requests are performed against a dedicated
      Memento domain, e.g., http://localhost:5000/memento/01992L0043.
      Obviously, the final service should seamlessly integrate with the
      existing URI scheme,
      e.g., http://publications.europa.eu/resource/celex/01992L0043.
    """
    response = None
    # restriction on celex id only in prototype
    uri = CELLAR_BASE + "/resource/celex/" + id
    # get URI of Original Resource
    uri_r = get_URI_R(uri)
    # return memento (target resource is not a complex work)
    if not(isEvolutiveWork(uri)):
        response = nonInformationResourceCallback(uri, uri_r)
    elif uri_r == uri and not('Accept-Datetime' in request.headers):
        response = nonInformationResourceCallback(uri, uri_r, 'accept-datetime')
    elif uri_r == uri and 'Accept-Datetime' in request.headers:
        response = originalTimegateCallback(uri)
    elif uri_r != uri:
        response = intermediateResourceCallBack(uri, uri_r)

    return response


@app.route('/data/<id>')
def processDataRequest(id=None):
    """Process data representation request (information resources)

      For simplicity, prototype requests are performed against a dedicated
      data domain, e.g., http://localhost:5000/data/01992L0043.xml.
      Obviously, the final service should seamlessly integrate with the
      existing URI scheme for information resources,
      such as branch and tree, e.g.,
      http://publications.europa.eu/resource/cellar/ef126686-ee90-48be-b8dd-a5386b64e468/xml/tree?decoding=en.

      This proof of concept considers only two possible serializations
      whose media-types are derived from the file extension. The final
      implementation should obviously not make this assumptions.
    """
    LOGGER.debug('Processing data request ...')
    response = None
    uri = CELLAR_BASE + "/resource/celex/" + id
    # restrictions on file endings only in prototype
    if id.endswith('.txt'):
        # return application/link-format
        response = dataRepresentationCallback(uri.replace('.txt', ''), True)
    else:
        # return application/rdf+xml
        response = dataRepresentationCallback(uri.replace('.xml', ''), False)
    return response


def originalTimegateCallback(uri_r):
    """Processing logic when requesting an original resource / timegate.
    """
    LOGGER.debug('Executing timegateCallback...')
    accept_datetime = None
    location = None
    # redirect to intermediate resource
    accept_datetime = parseHTTPDate(request.headers['Accept-Datetime'])
    LOGGER.debug('Accept-Datetime: %s' % accept_datetime)
    # compute location field of redirect
    location = determineLocationInPast(uri_r, accept_datetime)
    # redirect to most recent representation
    if location == None:
        location = determineLocationInFuture(uri_r, accept_datetime)
    # link headers

    localhost_uri_g = toLocalhostUri(uri_r)
    localhost_uri_t = toLocalhostDataUri(uri_r,'.txt')
    LOGGER.debug(localhost_uri_g)
    LOGGER.debug(localhost_uri_t)
    # return redirection object
    redirect_obj = redirect(toLocalhostUri(location), code=302)
    redirect_obj.headers['Link'] = '<%(localhost_uri_g)s>; rel="original timegate", ' \
        '<%(localhost_uri_t)s>; rel="timemap"' % {
            'localhost_uri_g': localhost_uri_g, 'localhost_uri_t': localhost_uri_t}
    redirect_obj.headers['Vary'] = 'accept-datetime'
    return redirect_obj


def intermediateResourceCallBack(uri, uri_r):
    """Processing logic when requesting an intermediate resource
       Intermediate resources behave like timegates but
       differ in their response headers.
    """
    LOGGER.debug('Executing intermediateResourceCallBack...')
    # default to now if no accept-datetime is provided
    accept_datetime = ('Accept-Datetime' in request.headers) and parseHTTPDate(request.headers[
        'Accept-Datetime']) or time.strftime("%Y-%m-%dT%X")
    # compute redirect
    location = determineLocationInPast(uri, accept_datetime)
    # if there is no redirect location in the past,
    # redirect to nearest resource in the future.
    if location == None:
        location = determineLocationInFuture(uri, accept_datetime)
    # link headers
    localhost_uri_r = toLocalhostUri(uri_r)
    localhost_uri_tr = toLocalhostDataUri(uri_r, '.txt')
    localhost_uri = toLocalhostUri(uri)
    localhost_uri_t = toLocalhostDataUri(uri,'.txt')
    LOGGER.debug(localhost_uri_r)
    LOGGER.debug(localhost_uri_tr)
    # return redirection object
    redirect_obj = redirect(toLocalRedirectUri(location), code=302)
    redirect_obj.headers['Link'] = '<%(localhost_uri_r)s>; rel="original timegate", ' \
        '<%(localhost_uri_tr)s>; rel="timemap", ' \
        '<%(localhost_uri_t)s>; rel="timemap" ' % {
            'localhost_uri_r': localhost_uri_r, 'localhost_uri_tr': localhost_uri_tr,
            'localhost_uri_t': localhost_uri_t}
    return redirect_obj


def nonInformationResourceCallback(uri, uri_r, vary=None):
    """Processing logic when requesting an individual work.
       From a memento point of view an individual work is also an intermediate resource.
    """
    LOGGER.debug('Executing nonInformationResourceCallback...')
    localhost_uri_r = toLocalhostUri(uri_r)
    localhost_uri_t = toLocalhostDataUri(uri_r,'.txt')
    # for simplification prototype redirects to RDF/XML representation
    # cellar implementation should of course integrate with existing
    # content negotiation.

    #if(request.headers['Accept']=='application/link-format'):
    if('application/link-format' in request.headers['Accept']):
        response=timemapCallback(uri, uri_r)
    else:
        related_predecessors_query = RELATED_PREDECESSORS % {'uri':uri}
        sparql_results = sparqlQuery(related_predecessors_query)
        response = redirect(toLocalRedirectDataUri(uri, '.xml'), code=303)
        response.headers['Link'] = '<%(localhost_uri_r)s>; rel="original timegate", ' \
            '<%(localhost_uri_t)s>; rel="timemap"' % {
                'localhost_uri_r': localhost_uri_r, 'localhost_uri_t': localhost_uri_t}
        response.headers['Link']+= ''.join([', <'+toLocalhostUri(i['predecessor']['value'])+'>; rel="'+PREDECESSOR_RELATION+'"; lang="'+(i['languages']['value'].lower())+'"' for i in sparql_results])
        if(vary is not None):
            response.headers['Vary'] = vary
    return response


def getMementoDatetime(uri):
    """Return memento-datetime for a given resource"""
    memento_datemtime_query = MEMENTO_DATETIME_TEMPLATE % {'uri': uri}
    #LOGGER.debug('MEMENTO_DATETIME_TEMPLATE: %s' % memento_datemtime_query )
    sparql_results = sparqlQuery(memento_datemtime_query)
    try:
        return sparql_results[0]['date']['value']
    except:
        return None


def timemapCallback(uri, uri_r):
    """Processing logic when requesting a timemap"""
    LOGGER.debug('Executing timemapCallback...')
    localhost_uri_r = toLocalhostUri(uri_r)
    localhost_uri_t = toLocalhostDataUri(uri_r,'.txt')
    redirect_obj = None
    type_attr = None
    # for simplification, only two timemap serializations are supported
    # by the prototype. In Cellar, requests on evolutive works with ?rel=timemap extension
    # should trigger the usual content negotiation mechanism. In addition, a new
    # serialization format (i.e., application/link-format) needs to be supported.
    if(request.headers['Accept'] == 'application/link-format'):
        # redirect to link-format representation
        redirect_obj = redirect(toLocalRedirectDataUri(uri, '.txt'), code=303)
        type_attr = 'application/link-format'
    else:
        # redirect to rdf/xml representation
        redirect_obj = redirect(toLocalRedirectDataUri(uri, '.xml'), code=303)
        type_attr = 'application/rdf+xml'
    # see section 5.1.2 of the Memento specification
    redirect_obj.headers['Link'] = '<%(localhost_uri_t)s>; ' \
                                   'rel="timemap"; ' \
                                   'type="%(type_attr)s"' % {
        'localhost_uri_r': localhost_uri_r,
        'localhost_uri_t': localhost_uri_t,
        'type_attr' : type_attr
        }
    return redirect_obj

def getFirstOrLastMemento(uri_g, flag):
    query = None
    if flag == 'first':
        query = FIRST_MEMENTO_TEMPLATE % {'uri': uri_g}
    elif flag == 'last':
        query = LAST_MEMENTO_TEMPLATE % {'uri': uri_g}
    else:
        raise Exception("Unknown argument for getFirstOrLastMemento")

    sparql_results = sparqlQuery(query)
    try:
        return {'date' : sparql_results[0]['date']['value'],
                'uri' : sparql_results[0]['individual_work']['value']
                }
    except:
        return None

def dataRepresentationCallback(uri, linkformat):
    """Processing logic when requesting a data representation (information resource)
       Prototype currently supports the following data representations: rdf/xml of
       individual works (mementos), rdf/xml and link-format of timemaps.
       Cellar implementation should support all existing types of representations.
    """
    LOGGER.debug('Executing dataRepresentationCallback...')
    uri_r = get_URI_R(uri)
    localhost_uri_r = toLocalhostUri(uri_r)
    localhost_uri_t = toLocalhostDataUri(uri_r,'.txt')
    if linkformat:
        tm = generateLinkformatTimemap(uri)
        response = make_response(tm, 200)
        response.headers['Content-Type'] = 'application/link-format; charset=utf-8'
    else:
        mdt = getMementoDatetime(uri)
        first_memento = getFirstOrLastMemento(uri_r, 'first')
        last_memento = getFirstOrLastMemento(uri_r, 'last')
        describe_query = DESCRIBE_TEMPLATE % {'uri': uri}
        sparql_results = sparqlQuery(
            describe_query, format='application/rdf+xml')
        response = make_response(sparql_results, 200)
        response.headers['Content-Type'] = 'application/rdf+xml; charset=utf-8'
        if mdt != None:
            response.headers['Memento-Datetime'] = stringToHTTPDate(mdt)
            response.headers['Link'] = '<%(localhost_uri_r)s>; rel="original timegate", ' \
            '<%(localhost_uri_t)s>; rel="timemap", ' \
            '<%(localhost_uri_first_memento)s>; rel="memento first"; datetime="%(first_memento_datetime)s", ' \
            '<%(localhost_uri_last_memento)s>; rel="memento last"; datetime="%(last_memento_datetime)s"' % {
            'localhost_uri_r': localhost_uri_r,
            'localhost_uri_t': localhost_uri_t,
            'localhost_uri_first_memento' : toLocalhostUri(first_memento['uri']),
            'first_memento_datetime' : stringToHTTPDate(first_memento['date']) ,
            'localhost_uri_last_memento' : toLocalhostUri(last_memento['uri']),
            'last_memento_datetime' : stringToHTTPDate(last_memento['date'])
            }
    return response


def generateLinkformatTimemap(uri):
    """Generate timemap in link-value format"""
    # get related timemaps
    query_tm = RELATED_EVOLUTIVE_WORKS % {'uri': uri}
    tm_results = sparqlQuery(query_tm)
    # get related original timegate
    query_ot = URI_R_TEMPLATE % {'uri': uri}
    ot_results = sparqlQuery(query_ot)
    # get related mementos
    query_m = RELATED_MEMENTOS % {'uri': uri}

    m_results = sparqlQuery(query_m)
    # get startdate, enddate and type of date
    timemap_list = [uri]
    timemap_list.append(uri)
    for i in tm_results:
        timemap_list.append(i['evolutive_work']['value'])
    timemap_info = {}
    for i in timemap_list:
        query_tminfo = TIMEMAPINFO % {'uri': i}
        tminfo_results = sparqlQuery(query_tminfo)
        timemap_info[toLocalhostUri(i)] = (stringToHTTPDate(tminfo_results[0]['startdate']['value']),
                                           stringToHTTPDate(
                                               tminfo_results[0]['enddate']['value']),
                                           tminfo_results[0]['typeofdate']['value'])
    # add link to the original timegate
    response_body = ''.join(
        ['<' + toLocalhostUri(i['predecessor']['value']) + '>;rel="original timegate"\n' for i in ot_results])
    # add link for each memento
    response_body += ''.join(['<' + toLocalhostUri(i['memento']['value']) +
                              '>;rel="memento";datetime="' + stringToHTTPDate(i['date']['value']) + '"\n' for i in m_results])
    # add link for timemaps
    response_body += ''.join(['<' + toLocalhostDataUri(i['evolutive_work']['value'],'.txt')
                              +
                              '>;rel="timemap";type="application/link-format"'
                              + ';from="' +
                              str(timemap_info[
                                  toLocalhostUri(i['evolutive_work']['value'])][0]) + '"'
                              + ';until="' +
                              str(timemap_info[
                                  toLocalhostUri(i['evolutive_work']['value'])][1]) + '"'
                              + ';dtype="' + str(timemap_info[toLocalhostUri(i['evolutive_work']['value'])][2]) + '"\n' for i in tm_results])
    # add link to self
    response_body += '<' + toLocalhostDataUri(uri,'.txt') + '>;rel="self";type="application/link-format"' \
                     + ';from="' + str(timemap_info[toLocalhostUri(uri)][0]) + '"' \
                     + ';until="' + str(timemap_info[toLocalhostUri(uri)][1]) + '"' \
                     + ';dtype="' + \
        str(timemap_info[toLocalhostUri(uri)][2]) + '"'
    return response_body


def isEvolutiveWork(uri):
    """Check whether the uri represents an instance of type cdm:evolutive_work"""
    query = EVOLUTIVE_WORK_TEMPLATE % {'uri': uri}
    #LOGGER.debug('EVOLUTIVE_WORK_TEMPLATE: %s' % query )
    sparql_results = sparqlQuery(query)
    LOGGER.debug(sparql_results == [])
    return sparql_results != []

def determineLocationInPast(uri, accept_datetime):
    """Determine the location information for next redirect (search in past)"""
    query = LOCATION_TEMPLATE_NEAREST_IN_PAST % {
        'uri': uri, 'accept_datetime': accept_datetime}
    #LOGGER.debug('LOCATION_TEMPLATE: %s' % query )
    sparql_results = sparqlQuery(query)
    location = None
    try:
        location = sparql_results[0]['successor']['value']
    except:
        LOGGER.debug(
            'determineLocation: Could not determine redirect location...')
    LOGGER.debug("Location: %s" % location)
    return location

def determineLocationInFuture(uri, accept_datetime):
    """Determine the location information for next redirect (search in future)"""
    query = LOCATION_TEMPLATE_NEAREST_IN_FUTURE % {
        'uri': uri, 'accept_datetime': accept_datetime}
    #LOGGER.debug('LOCATION_TEMPLATE: %s' % query )
    sparql_results = sparqlQuery(query)
    location = None
    try:
        location = sparql_results[0]['successor']['value']
    except:
        LOGGER.debug(
            'determineLocation: Could not determine redirect location...')
    LOGGER.debug("Location: %s" % location)
    return location


def toCelexUri(uri):
    """Transform a local memento uri into celex uri"""
    # Prototype uses cellar1-dev as placeholder for all production systems.
    # Prototype only supports celex PSIs. Cellar implementation should support all
    # production systems and PSIs.
    return uri.replace('memento', CELLAR_BASE + '/resource/celex')


def toLocalRedirectUri(uri):
    """Transform a celex uri into a relative, local,  memento uri"""
    return uri.replace(CELLAR_BASE + '/resource/celex', 'memento')


def toLocalRedirectDataUri(uri, fext):
    """Transform a celex uri into a relative, local, data uri"""
    return uri.replace(CELLAR_BASE + '/resource/celex', 'data') + fext


def toLocalhostUri(uri):
    """Transform a celex uri into an absolute, local, memento uri"""
    return uri.replace(CELLAR_BASE + '/resource/celex',
                       '%(localhost)s/memento' % {'localhost': local_host})


def toLocalhostDataUri(uri, fext):
    """Transform a celex uri into an absolute, local, data uri"""
    return uri.replace(CELLAR_BASE + '/resource/celex',
                       '%(localhost)s/data' % {'localhost': local_host}) + fext


def parseHTTPDate(text):
    """Parse a HTTP-date and return a datetime object"""
    # parse UTC datetime from text (value of Accept-Datetime)
    utc_dt = datetime.datetime(*eut.parsedate(text)[:6], tzinfo=timezone('UTC'))
    # transform UTC datetime into local time
    local_dt = utc_dt.astimezone(timezone('Europe/Luxembourg'))
    # return local datetime without timezone information for further processing in virtuoso
    dt = datetime.datetime(local_dt.year, local_dt.month, local_dt.day,
                           local_dt.hour, local_dt.minute, local_dt.second)
    dt = dt.isoformat(sep='T')
    return dt


def stringToHTTPDate(text):
    """Convert a xsd:date into an HTTP-date string"""
    # parse datetime from text (SPARQL result). Supported formats are: %Y-%m-%d %H:%M:%S and %Y-%m-%d
    try:
        dt = datetime.datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        dt = datetime.datetime.strptime(text, '%Y-%m-%d')
    # localize datetime (set timezone to CET/CEST)
    local_dt = pytz.timezone('Europe/Luxembourg').localize(
        datetime.datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
    # transform localized datetime into UTC datetime
    utc_dt = local_dt.astimezone(timezone('UTC'))
    return utc_dt.strftime('%a, %d %b %Y %H:%M:%S') + (' GMT')

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    # set logging format
    logFormatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5.5s]  %(message)s")
    # create LOGGER
    global LOGGER
    LOGGER = logging.getLogger()
    # set up file logging
    fileHandler = logging.handlers.RotatingFileHandler(
        "logging.log", maxBytes=1000000000, backupCount=2)
    fileHandler.setFormatter(logFormatter)
    LOGGER.addHandler(fileHandler)
    # set up console logging
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    LOGGER.addHandler(consoleHandler)
    app.run(debug=True)
