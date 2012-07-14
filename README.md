# RESTful OpenERP

## Introduction

[OpenERP](http://www.openerp.com/) is a powerful Open Source Software for Enterprise Resource Planning (ERP). It has a GTK desktop client and a web interface, both talking to the OpenERP backend via [XML-RPC](http://en.wikipedia.org/wiki/XML-RPC). This also allows to write third-party applications that use OpenERP functionality - however, not in a RESTful way.

The aim of this project is to provide a RESTful "proxy" for OpenERP's XML-RPC web service. We aim to build the API in such a way that

* it becomes a lot easier for third party applications to talk to OpenERP (by making the API easily understandable and providing hyperlinks to linked resources and workflows) and  
* to allow to make OpenERP the primary data source for services (by making results cacheable as much as possible).

## Status

Currently it is possible to get

* for all object types defined within OpenERP (e.g., `res.partner`), a list of all objects of this type at `/{database}/{model}` as an Atom feed,
* for all object types defined within OpenERP, a complete description of each individual object at the URI specified in the above feed (usually `/{database}/{model}/{id}`) as an Atom entry,
* for all object types defined within OpenERP, a description of the schema of this object type at `/{database}/{model}/schema` as n Relax NG XML description.

Access control is done via HTTP Basic Auth using OpenERP as backend. There is a good test coverage of HTTP response codes, XML validity etc.

To illustrate:

`curl -u user:pass http://localhost:8068/erptest/res.partner` gives

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">res.partner items</title>
  <id>http://localhost:8068/erptest/res.partner</id>
  <updated>2012-04-07T19:28:54Z</updated>
  <generator>PyAtom</generator>
  <entry>
    <title type="text">Amazon EU S.a.r.L.</title>
    <id>http://localhost:8068/erptest/res.partner/4</id>
    <updated>2012-03-19T15:45:17Z</updated>
    <link href="http://localhost:8068/erptest/res.partner/4" />
    <author>
      <name>None</name>
    </author>
  </entry>
  <entry>
    <title type="text">DHL GmbH</title>
    <id>http://localhost:8068/erptest/res.partner/3</id>
    <updated>2012-03-19T15:44:59Z</updated>
    <link href="http://localhost:8068/erptest/res.partner/3" />
    <author>
      <name>None</name>
    </author>
  </entry>
  ...
</feed>
```

`curl -u user:pass http://localhost:8068/erptest/res.partner/4` gives

```xml
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">Amazon EU S.a.r.L.</title>
  <id>http://localhost:8068/erptest/res.partner/4</id>
  <updated>2012-03-19T15:45:17Z</updated>
  <link href="http://localhost:8068/erptest/res.partner/4" rel="self" />
  <author>
    <name>None</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <res_partner xmlns="http://localhost:8068/erptest/res.partner/schema">
    <id>4</id>
    <name type='char'>Amazon EU S.a.r.L.</name>
    <supplier type='boolean'>True</supplier>
    <customer type='boolean'>False</customer>
    <company_id type='many2one'>
      <link href='http://localhost:8068/erptest/res.company/1' />
    </company_id>
    <address type='one2many'>
      <link href="http://localhost:8068/erptest/res.partner.address/4" />
    </address>
    ...
  </res_partner>
  </content>
</entry>
```

`curl -u user:pass http://localhost:8068/erptest/res.partner/schema` gives

```xml
<?xml version="1.0" encoding="utf-8"?>
<element name="res_partner" xmlns="http://relaxng.org/ns/structure/1.0" datatypeLibrary="http://www.w3.org/2001/XMLSchema-datatypes" ns="http://localhost:8068/erptest/res.partner/schema">
<interleave>
  <element name="id"><data type="decimal" /></element>
  <element name="name">
    <attribute name="type" />
    <data type="string"><param name="minLength">1</param></data>
  </element>
  <element name="supplier">
    <attribute name="type" />
    <optional><choice><value>True</value><value>False</value></choice></optional>
  </element>
  <element name="customer">
    <attribute name="type" />
    <optional><choice><value>True</value><value>False</value></choice></optional>
  </element>
  <element name="company_id">
    <attribute name="type" />
    <optional><element name="link"><attribute name="href" /></element></optional>
  </element>
  <element name="address">
    <attribute name="type" />
    <zeroOrMore><element name="link"><attribute name="href" /></element></zeroOrMore>
  </element>
  ...
</interleave>
</element>
```

## Roadmap

See issues.

## Dependencies

* [Twisted](http://twistedmatrix.com/trac/) >= 10.1
* [PyAtom](https://github.com/sramana/pyatom)
* [python-dateutil](http://labix.org/python-dateutil)
* [lxml](http://lxml.de/)

There is a requirements.txt file for pip that can be used to satisfy the dependencies.

## Installation

To install restful-openerp in a Python virtualenv, do as follows:

* `git clone git://github.com/tgpfeiffer/restful-openerp.git`
* `cd restful-openerp/`
* `virtualenv --no-site-packages .env`
* `. .env/bin/activate`
* `pip install -r requirements.txt` (note that you will have to have libxslt1-dev and libxml2-dev installed to build lxml)
* `cp restful-openerp.cfg.default restful-openerp.cfg` and edit `restful-openerp.cfg` to contain the proper URL of your OpenERP XML-RPC endpoint (default: a locally running instance). If you want to run the unit tests, also give a valid username/password for your OpenERP instance in there.
* `trial basicTests` should now run a list of unit tests (that hopefully all pass)
* `python restfulOpenErpProxy.py` runs the actual server process

## License

AGPLv3 for now. Will maybe change later.
