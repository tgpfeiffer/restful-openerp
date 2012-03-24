# RESTful OpenERP

## Introduction

[OpenERP](http://www.openerp.com/) is a powerful Open Source Software for Enterprise Resource Planning (ERP). It has a GTK desktop client and a web interface, both talking to the OpenERP backend via [XML-RPC](http://en.wikipedia.org/wiki/XML-RPC). This also allows to write third-party applications that use OpenERP functionality - however, not in a RESTful way.

The aim of this project is to provide a RESTful "proxy" for OpenERP's XML-RPC web service.

## Status

It is currently possible to obtain a list of object IDs by issuing

    GET /{database}/{model}

For example:

    $ curl -u user:pass http://localhost:8068/erptest/res.partner
    [4, 3, 8, 5, 7, 6, 9, 10, 1, 2]

The service will respond with HTTP 403 if user/pass is wrong or not present, and with HTTP 500 if something went wrong.

## Roadmap

* Return a proper list of URIs instead of IDs and allow to obtain single objects as XML by issuing "GET /{database}/{model}/{id}".
* In the returned XML, use the URIs of referenced resources instead of just their IDs.
* Add caching for GET requests; provide an XML-RPC proxy to OpenERP for write-requests that invalidates the cache.
* Allow to add and edit resources via POST/PUT, i.e. make it a proper CRU interface (no 'D' though).
* Create a "Level Three" webservice (cf. Webber/Parastatidis/Robinson: "REST in Practice") that includes in each reply links to related resources, thereby allowing to follow the workflows defined in OpenERP.

## License

AGPLv3 for now. Will maybe change later.
