# RESTful OpenERP

## Introduction

[OpenERP](http://www.openerp.com/) is a powerful Open Source Software for Enterprise Resource Planning (ERP). It has a GTK desktop client and a web interface, both talking to the OpenERP backend via [XML-RPC](http://en.wikipedia.org/wiki/XML-RPC). This also allows to write third-party applications that use OpenERP functionality - however, not in a RESTful way.

The aim of this project is to provide a RESTful "proxy" for OpenERP's XML-RPC web service.

## Status

It is currently possible to obtain a list of objects by issuing

    GET /{database}/{model}

For example:

    $ curl -u user:pass http://localhost:8068/erptest/res.partner
    <?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title type="text">res.partner items</title>
      <id>res.partner</id>
      <updated>2012-04-07T06:53:29Z</updated>
      <generator>PyAtom</generator>
      <entry>
        <title type="text">Some Partner</title>
        <id>http://localhost:8068/erptest/res.partner/4</id>
        <updated>2012-03-19T15:45:17Z</updated>
        <link href="http://localhost:8068/erptest/res.partner/4" />
        <author>
          <name></name>
        </author>
      </entry>
      ...
    </<feed>

The service will respond with HTTP response code 403 if user/pass is wrong, 401 if user/pass not present, and with HTTP 500 if something went wrong.

## Roadmap

* <strike>Return a proper list of URIs instead of IDs and allow to obtain single objects as XML by issuing "GET /{database}/{model}/{id}".</strike>
* In the returned XML, use the URIs of referenced resources instead of just their IDs.
* Add caching for GET requests; provide an XML-RPC proxy to OpenERP for write-requests that invalidates the cache.
* Allow to add and edit resources via POST/PUT, i.e. make it a proper CRU interface (no 'D' though).
* Create a "Level Three" webservice (cf. Webber/Parastatidis/Robinson: "REST in Practice") that includes in each reply links to related resources, thereby allowing to follow the workflows defined in OpenERP.

## Dependencies

* [Twisted](http://twistedmatrix.com/trac/)
* [PyAtom](https://github.com/sramana/pyatom)
* [python-dateutil](http://labix.org/python-dateutil)

## License

AGPLv3 for now. Will maybe change later.
