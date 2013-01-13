# RESTful OpenERP

[![Build Status](https://travis-ci.org/tgpfeiffer/restful-openerp.png?branch=master)](https://travis-ci.org/tgpfeiffer/restful-openerp)

## Introduction

[OpenERP](http://www.openerp.com/) is a powerful Open Source Software for Enterprise Resource Planning (ERP). It has a GTK desktop client and a web interface, both talking to the OpenERP backend via [XML-RPC](http://en.wikipedia.org/wiki/XML-RPC). This also allows to write third-party applications that use OpenERP functionality – however, not in a RESTful way.

The aim of this project is to provide a RESTful “proxy” for OpenERP's XML-RPC web service. We aim to build the API in such a way that

* it becomes a lot easier for third party applications to talk to OpenERP (by making the API easily understandable and providing hyperlinks to linked resources and workflows) and  
* to allow to make OpenERP the primary data source for services (by making results cacheable as much as possible).

## Status

Currently it is possible to get

* for all object types defined within OpenERP (e.g., `res.partner`), a **list of all objects** of this type at `/{database}/{model}` as an Atom feed,
* a **filtered version of that list** using `/{database}/{model}?{key}={value}`,
* for all object types defined within OpenERP, a **complete description of each object** at the URI specified in the above feed (usually `/{database}/{model}/{id}`) as an Atom entry,
* a **parameterized version of that description** for general environment parameters such as “lang” or “tz” or special context-dependent parameters such as “product_id” using `/{database}/{model}/{id}?{key}={value}`,
* for all object types defined within OpenERP, a description of the **schema of this object type** at `/{database}/{model}/schema` as a Relax NG XML description,
* for all object types defined within OpenERP, the **default values for this object type** at `/{database}/{model}/defaults`.

Also, it is possible to create, for all object types defined within OpenERP (e.g., `res.partner`), a **new object** of this type by POSTing an appropriate description to `/{database}/{model}`. Such a description can in particular be obtained by taking the XML from `/{database}/{model}/defaults`, extracting the OpenERP-specific fragment (e.g., the `res_partner` node) and setting the body of all required elements.

Access control is done via HTTP Basic Auth using OpenERP as backend. There is a good test coverage of HTTP response codes, XML validity etc.

To illustrate:

### List of all objects

`curl -u user:pass http://localhost:8068/erptest/product.product` gives:

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">product.product items</title>
  <id>http://localhost:8068/erptest/product.product</id>
  <updated>2012-07-04T12:56:07Z</updated>
  <generator>PyAtom</generator>
  <entry>
    <title type="text">MESH (german)</title>
    <id>http://localhost:8068/erptest/product.product/147</id>
    <updated>2012-05-31T13:25:06Z</updated>
    <link href="http://localhost:8068/erptest/product.product/147" />
    <author>
      <name>None</name>
    </author>
  </entry>
  <entry>
    <title type="text">Is God a Number?</title>
    <id>http://localhost:8068/erptest/product.product/179</id>
    <updated>2012-06-13T08:05:54Z</updated>
    <link href="http://localhost:8068/erptest/product.product/179" />
    <author>
      <name>None</name>
    </author>
  </entry>
  ...
</feed>
```

`curl -u user:pass http://localhost:8068/erptest/product.product?default_code=01-2037-01` gives:

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">product.product items</title>
  <id>http://localhost:8068/erptest/product.product</id>
  <updated>2012-05-31T13:25:06Z</updated>
  <generator>PyAtom</generator>
  <entry>
    <title type="text">MESH (german)</title>
    <id>http://localhost:8068/erptest/product.product/147</id>
    <updated>2012-05-31T13:25:06Z</updated>
    <link href="http://localhost:8068/erptest/product.product/147" />
    <author>
      <name>None</name>
    </author>
  </entry>
</feed>
```

### Single object description

`curl -u user:pass http://localhost:8068/erptest/product.product/147` gives:

```xml
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">MESH (german)</title>
  <id>http://localhost:8068/erptest/product.product/147</id>
  <updated>2012-05-31T13:25:06Z</updated>
  <link href="http://localhost:8068/erptest/product.product/147" rel="self" />
  <author>
    <name>None</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <product_product xmlns="http://localhost:8068/erptest/product.product/schema">
    <ean13 type='char'>9783540853305</ean13>
    <code type='char'>01-2037-01</code>
    <incoming_qty type='float'><!-- 0.0 --></incoming_qty>
    <name_template type='char'><!-- False --></name_template>
    <company_id type='many2one'>
      <link href='http://localhost:8068/erptest/res.company/1' />
    </company_id>
    ...
  </product_product>
  </content>
</entry>
```

`curl -u user:pass http://localhost:8068/erptest/product.product/147?lang=de_DE` gives (note the translated title):

```xml
<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">MESH (deutsch)</title>
  <id>http://localhost:8068/erptest/product.product/147</id>
  <updated>2012-05-31T13:25:06Z</updated>
  <link href="http://localhost:8068/erptest/product.product/147" rel="self" />
  <author>
    <name>None</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <product_product xmlns="http://localhost:8068/erptest/product.product/schema">
    <ean13 type='char'>9783540853305</ean13>
    <code type='char'>01-2037-01</code>
    <incoming_qty type='float'><!-- 0.0 --></incoming_qty>
    <name_template type='char'><!-- False --></name_template>
    <company_id type='many2one'>
      <link href='http://localhost:8068/erptest/res.company/1' />
    </company_id>
    ...
  </product_product>
  </content>
</entry>
```

### Schema

`curl -u user:pass http://localhost:8068/erptest/product.product/schema` gives:

```xml
<?xml version="1.0" encoding="utf-8"?>
<element name="res_partner" xmlns="http://relaxng.org/ns/structure/1.0" datatypeLibrary="http://www.w3.org/2001/XMLSchema-datatypes" ns="http://localhost:8068/erptest/res.partner/schema">
<interleave>
  <element name="id"><data type="decimal" /></element>
  <element name="ean13">
    <attribute name="type" />
    <optional><text /></optional>
  </element>
  <element name="code">
    <attribute name="type" />
    <optional><text /></optional>
  </element>
  <element name="incoming_qty">
    <attribute name="type" />
    <optional><data type="double" /></optional>
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
* pyOpenSSL (optional, needed to access OpenERP via https)

There is a requirements.txt file for pip that can be used to satisfy the required dependencies.

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
