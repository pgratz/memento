#!/bin/bash

# Request memento with constant Accept-Datetime value set to Sun, 10 Nov 2012 12:00:0 GMT (no modifications between the redirects)
curl -L --dump-header "response_headers1.txt" --header "Accept-Datetime:Sat, 10 Nov 2012 12:00:0 GMT" "http://localhost:5000/memento/01992L0043"

# Request memento with adaptation of the Accept-Datetime for the intermediate resource (datetime_negotiation = work_date_creation)
curl --dump-header "response_headers2.txt" --header "Accept-Datetime:Sat, 10 Nov 2012 12:00:0 GMT" "http://localhost:5000/memento/01992L0043"

# Adapt Accept-Datetime to a suitable value for work_date_creation. Information via the negotiated date can be retrieved from the timemap.
curl -L --dump-header "response_headers3.txt" --header "Accept-Datetime:Mon, 10 Nov 2014 12:00:0 GMT" "http://localhost:5000/memento/01992L0043-20040501"

# Request the most recent version without specifying an ADT.
curl -L --dump-header "response_headers4.txt" "http://localhost:5000/memento/01992L0043"

# Request a memento with a Accept-Datetime < the earliest negotiable work.
curl -L --dump-header "response_headers5.txt" --header "Accept-Datetime:Tue, 01 Jul 2003 12:00:0 GMT" "http://localhost:5000/memento/01992L0043"

# Request timemap in link format
curl -L --dump-header "response_headers6.txt" --header "Accept:application/link-format" "http://localhost:5000/memento/01992L0043?rel=timemap"

# Request "timemap" in rdf/xml format (default)
curl -L --dump-header "response_headers7.txt" "http://localhost:5000/memento/01992L0043?rel=timemap"