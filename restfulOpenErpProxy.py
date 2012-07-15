#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser, datetime, dateutil.tz, inspect
from xml.sax.saxutils import escape as xmlescape

from lxml import etree

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import *
from twisted.internet import reactor, task
from twisted.python import log
from twisted.web.xmlrpc import Proxy

import pyatom

def hello():
  """If you wanted, you could log some message from here to understand the
call stack a bit better..."""
  stack = inspect.stack()
  parent = stack[1][3]

def localTimeStringToUtcDatetime(s):
  # get local and UTC timezone to convert the time stamps
  tz=dateutil.tz.tzlocal()
  utc=dateutil.tz.tzutc()
  t = datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S.%f') # this time is in local tz
  t_withtz = t.replace(tzinfo=tz)
  return t_withtz.astimezone(utc)

def httpdate(dt):
  return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

class UnauthorizedPage(ErrorPage):
  def __init__(self):
    ErrorPage.__init__(self, 401, "Unauthorized", "Use HTTP Basic Authentication!")
  def render(self, request):
    r = ErrorPage.render(self, request)
    request.setHeader("WWW-Authenticate", 'Basic realm="OpenERP"')
    return r


class OpenErpDispatcher(Resource, object):
  databases = {}
  
  def __init__(self, openerpUrl):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    log.msg("Server starting up with backend: " + self.openerpUrl)

  # @override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChildWithDefault
  def getChildWithDefault(self, pathElement, request):
    """Ensure that we have HTTP Basic Auth."""
    if not (request.getUser() and request.getPassword()):
      return UnauthorizedPage()
    else:
      return super(OpenErpDispatcher, self).getChildWithDefault(pathElement, request)
  
  # @override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChild
  def getChild(self, path, request):
    """Return a resource for the correct database."""
    if self.databases.has_key(path):
      return self.databases[path]
    else:
      log.msg("Creating resource for '%s' database." % path)
      self.databases[path] = OpenErpDbResource(self.openerpUrl, path)
      return self.databases[path]


class OpenErpDbResource(Resource):
  """This is accessed when going to /{database}."""
  def __init__(self, openerpUrl, dbname):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    self.dbname = dbname
  
  # @override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChild
  def getChild(self, path, request):
    return OpenErpModelResource(self.openerpUrl, self.dbname, path)


class OpenErpModelResource(Resource):
  isLeaf = True

  """This is accessed when going to /{database}/{model}."""
  def __init__(self, openerpUrl, dbname, model):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    self.dbname = dbname
    self.model = model
    self.desc = {}

  ### list items of a collection

  def __getCollection(self, uid, request, pwd):
    """This is called after successful login to list the items
    of a certain collection, e.g. all res.partners."""
    hello()
    params = []
    for key, vals in request.args.iteritems():
      if not self.desc.has_key(key) and key != "id":
        raise InvalidParameter("field '%s' not present in model '%s'" % (key, self.model))
      else:
        params.append((key, '=', vals[0]))
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'search', params)
    d.addCallback(self.__handleCollectionAnswer, request, uid, pwd)
    return d

  def __handleCollectionAnswer(self, val, request, uid, pwd):
    hello()

    def createFeed(items, request):
      # build a feed
      # TODO: add the feed url; will currently break the test
      feed = pyatom.AtomFeed(title=self.model+" items",
                             id=str(request.URLPath()),
                             #feed_url=str(request.URLPath())
                             )
      for item in items:
        if item.has_key('user_id') and item['user_id']:
          feed.add(title=item['name'],
                 url="%s/%s" % (request.URLPath(), item['id']),
                 updated=localTimeStringToUtcDatetime(item['__last_update']),
                 author=[{'name': item['user_id'][1]}])
        else:
          feed.add(title=item['name'],
                 url="%s/%s" % (request.URLPath(), item['id']),
                 updated=localTimeStringToUtcDatetime(item['__last_update']),
                 author=[{'name': 'None'}])
      request.setHeader("Content-Type", "application/atom+xml")
      request.write(str(feed.to_string().encode('utf-8')))
      request.finish()

    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', val, ['name', '__last_update', 'user_id'])
    d.addCallback(createFeed, request)
    return d

  ### get __last_update of a collection item

  def __getLastItemUpdate(self, uid, request, pwd, modelId):
    hello()
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    proxy = Proxy(self.openerpUrl + 'object')
    def handleLastItemUpdateAnswer(updateAnswer):
      return (uid, updateAnswer[0]['__last_update'])
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], ['__last_update'])
    d.addCallback(handleLastItemUpdateAnswer)
    return d

  ### list the default values for an item

  def __getItemDefaults(self, uid, request, pwd):
    hello()
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'default_get', self.desc.keys())
    d.addCallback(self.__handleItemDefaultsAnswer, request)
    return d

  def __handleItemDefaultsAnswer(self, item, request):
    hello()
    # set correct headers
    request.setHeader("Content-Type", "application/atom+xml")
    # compose answer
    request.write('''<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">Defaults for %s</title>
  <id>%s</id>
  <updated>%s</updated>
  <link href="%s" rel="self" />
  <author>
    <name>%s</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <%s xmlns="%s">
    <id />
''' % (self.model,
       str(request.URLPath())+"/defaults",
       datetime.datetime.utcnow().isoformat()[:-7]+'Z',
       str(request.URLPath())+"/defaults",
       'None',
       self.model.replace('.', '_'),
       '/'.join(str(request.URLPath()).split("/") + ["schema"]),
       ))
    # loop over the fields of the current object
    for key in self.desc.iterkeys():
      value = item.has_key(key) and item[key] or ""
      # key is the name of the field, value is the content,
      #  e.g. key="email", value="me@privacy.net"
      if self.desc.has_key(key):
        fieldtype = self.desc[key]['type']
        # if we have an empty field, we display a closed tag
        #  (except if this is a boolean field)
        if not value and fieldtype != "boolean":
          request.write("    <%s type='%s' />\n" % (
            key,
            fieldtype)
          )
        # display URIs for many2one fields
        elif fieldtype == 'many2one':
          request.write("    <%s type='%s'>\n      <link href='%s' />\n    </%s>\n" % (
            key,
            fieldtype,
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"], str(value)]),
            key)
          )
        # display URIs for *2many fields, wrapped by <item>
        elif fieldtype in ('one2many', 'many2many'):
          request.write("    <%s type='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            ''.join(
              ['\n      <link href="' + '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"], str(v)]) + '" />' for v in value]
            ) + '\n    ',
            key)
          )
        # for other fields, just output the data
        elif fieldtype == 'boolean':
          request.write("    <%s type='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            xmlescape(str(value and "True" or "False")),
            key)
          )
        else:
          request.write("    <%s type='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            xmlescape(str(value)),
            key)
          )
      else: # no type given or no self.desc present
        request.write("    <%s>%s</%s>\n" % (
          key,
          xmlescape(str(value)),
          key)
        )
    request.write("  </%s>\n  </content>\n</entry>" % self.model.replace('.', '_'))
    request.finish()

  ### list one particular item of a collection

  def __getItem(self, (uid, updateTime), request, pwd, modelId):
    hello()
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    # we add 'context' parameters, like 'lang' or 'tz'
    params = {}
    for key, vals in request.args.iteritems():
      try:
        val = int(vals[0])
      except:
        val = vals[0]
      params[key] = val
      if key == "active_id":
        params["active_ids"] = [val]
    # issue the request
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], [], params)
    d.addCallback(self.__handleItemAnswer, request, localTimeStringToUtcDatetime(updateTime))
    return d

  def __handleItemAnswer(self, val, request, lastModified):
    hello()
    # val should be a one-element-list with a dictionary describing the current object
    try:
      item = val[0]
    except IndexError, e:
      request.setResponseCode(404)
      request.write("No such resource.")
      request.finish()
      return

    # set correct headers
    request.setHeader("Last-Modified", httpdate(lastModified))
    request.setHeader("Content-Type", "application/atom+xml")
    # compose answer
    xmlHead = u'''<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">%s</title>
  <id>%s</id>
  <updated>%s</updated>
  <link href="%s" rel="self" />
  <author>
    <name>%s</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <%s xmlns="%s">
''' % (item['name'],
       str(request.URLPath())+"/"+str(item['id']),
       lastModified.isoformat()[:-13]+'Z',
       str(request.URLPath())+"/"+str(item['id']),
       'None', # TODO: insert author, if present
       self.model.replace('.', '_'),
       '/'.join(str(request.URLPath()).split("/") + ["schema"]),
       )
    request.write(xmlHead.encode('utf-8'))
    # loop over the fields of the current object
    for key, value in item.iteritems():
      # key is the name of the field, value is the content,
      #  e.g. key="email", value="me@privacy.net"
      if self.desc.has_key(key):
        fieldtype = self.desc[key]['type']
        # if we have an empty field, we display a closed tag
        #  (except if this is a boolean field)
        if not value and fieldtype != "boolean":
          request.write("    <%s type='%s'><!-- %s --></%s>\n" % (
            key,
            fieldtype,
            value,
            key)
          )
        # display URIs for many2one fields
        elif fieldtype == 'many2one':
          request.write("    <%s type='%s'>\n      <link href='%s' />\n    </%s>\n" % (
            key,
            fieldtype,
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"], str(value[0])]),
            key)
          )
        # display URIs for *2many fields, wrapped by <item>
        elif fieldtype in ('one2many', 'many2many'):
          request.write("    <%s type='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            ''.join(
              ['\n      <link href="' + '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"], str(v)]) + '" />' for v in value]
            ) + '\n    ',
            key)
          )
        # for other fields, just output the data
        else:
          request.write("    <%s type='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            xmlescape(unicode(value).encode('utf-8')),
            key)
          )
      else: # no type given or no self.desc present
        request.write("    <%s>%s</%s>\n" % (
          key,
          xmlescape(unicode(value).encode('utf-8')),
          key)
        )
    request.write("  </%s>\n  </content>\n</entry>" % self.model.replace('.', '_'))
    request.finish()

  ### handle inserts into collection

  def __addToCollection(self, uid, request, pwd):
    """This is called after successful login to add an items
    to a certain collection, e.g. a new res.partner."""
    hello()
    if not self.desc:
      raise xmlrpclib.Fault("warning -- Object Error", "no such collection")
    # check whether we got well-formed XML
    try:
      doc = etree.fromstring(request.content.read())
    except Exception as e:
      request.setResponseCode(400)
      request.write("malformed XML: "+str(e))
      request.finish()
      return
    # TODO: check whether we got valid XML with the given schema
    # TODO: transform XML content into XML-RPC call
    raise NotImplementedError

  ### handle login

  def __handleLoginAnswer(self, uid):
    hello()
    if not uid:
      raise xmlrpclib.Fault("AccessDenied", "login failed")
    else:
      return uid

  ### update the model information

  def __updateTypedesc(self, uid, pwd):
    hello()
    if not self.desc:
      # update type description
      proxy = Proxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'fields_get', [])
      d.addCallback(self.__handleTypedescAnswer, uid)
      d.addErrback(self.__handleTypedescError, uid)
      return d
    else:
      return uid

  def __handleTypedescAnswer(self, val, uid):
    hello()
    self.desc = val
    return uid

  def __handleTypedescError(self, err, uid):
    hello()
    # if an error appears while updating the type description
    return uid

  def __getSchema(self, uid, request):
    hello()
    if not self.desc:
      request.setResponseCode(404)
      request.write("Schema description not found")
      request.finish()
      return
    else:
      ns = str(request.URLPath()) + "/schema"
      request.write('''<?xml version="1.0" encoding="utf-8"?>
<element name="%s" xmlns="http://relaxng.org/ns/structure/1.0" datatypeLibrary="http://www.w3.org/2001/XMLSchema-datatypes" ns="%s">
<interleave>
  <element name="id"><data type="decimal" /></element>
''' % (self.model.replace(".", "_"), ns))
      for key, val in self.desc.iteritems():
        fieldtype = val['type']
        required = val.has_key('required') and val['required'] or False
        request.write('  <element name="%s">\n    <attribute name="type" />' % key)
        if fieldtype in ('many2many', 'one2many'):
          elemName = required and "oneOrMore" or "zeroOrMore"
          request.write('\n    <%s><element name="link"><attribute name="href" /></element></%s>\n  ' % (elemName, elemName))
        else:
          output = "\n    "
          # select the correct field type
          if fieldtype == "many2one":
            s = '<element name="link"><attribute name="href" /></element>'
            output += required and s or "<optional>"+s+"</optional>"
          elif fieldtype == "float":
            s = '<data type="double" />'
            output += required and s or "<optional>"+s+"</optional>"
          elif fieldtype == "boolean":
            s = '<choice><value>True</value><value>False</value></choice>'
            output += required and s or "<optional>"+s+"</optional>"
          elif fieldtype == "integer":
            s = '<data type="decimal" />'
            output += required and s or "<optional>"+s+"</optional>"
          else:
            s = required and '<data type="string"><param name="minLength">1</param></data>' or \
              "<optional><text /></optional>"
            output += s
          request.write(output+'\n  ')
        request.write('</element>\n')
      request.write('</interleave>\n</element>')
      #request.write(self.desc.__repr__())
      request.finish()

  ### error handling

  def __cleanup(self, err, request):
    hello()
    log.msg(err)
    request.setHeader("Content-Type", "text/plain")
    e = err.value
    if err.check(xmlrpclib.Fault):
      if e.faultCode == "AccessDenied":
        request.setResponseCode(403)
        request.write("Bad credentials.")
      elif e.faultCode.startswith("warning -- AccessError"):
        # the above results from a xmlrpclib problem: error message in faultCode
        request.setResponseCode(404)
        request.write("No such resource.")
      elif e.faultCode.startswith("warning -- Object Error"):
        request.setResponseCode(404)
        request.write("No such collection.")
      else:
        request.setResponseCode(500)
        request.write("An XML-RPC error occured:\n"+e.faultCode)
    elif e.__class__ in (InvalidParameter, PostNotPossible, NoChildResources):
      request.setResponseCode(e.code)
      request.write(str(e))
    else:
      request.setResponseCode(500)
      request.write("An error occured:\n"+str(e))
    request.finish()

  def __raiseAnError(self, *params):
    """This function is necessary as errors are only caught by errbacks
if they are thrown from within callbacks, not directly from render_GET.
It only throws the given exception."""
    e = params[-1]
    raise e

  ### HTTP request handling
    
  def render_GET(self, request):
    hello()
    user = request.getUser()
    pwd = request.getPassword()

    # login to OpenERP
    proxyCommon = Proxy(self.openerpUrl + 'common')
    d = proxyCommon.callRemote('login', self.dbname, user, pwd)
    d.addCallback(self.__handleLoginAnswer)
    d.addCallback(self.__updateTypedesc, pwd)

    # if uri is sth. like /[dbname]/res.partner,
    #  give a list of all objects in this collection:
    if not request.postpath:
      d.addCallback(self.__getCollection, request, pwd)

    # if URI is sth. like /[dbname]/res.partner/schema,
    #  list this particular schema
    elif len(request.postpath) == 1 and request.postpath[0] == "schema":
      d.addCallback(self.__getSchema, request)

    # if URI is sth. like /[dbname]/res.partner/defaults,
    #  list this particular schema
    elif len(request.postpath) == 1 and request.postpath[0] == "defaults":
      d.addCallback(self.__getItemDefaults, request, pwd)

    # if URI is sth. like /[dbname]/res.partner/7,
    #  list this particular item
    elif len(request.postpath) == 1:
      d.addCallback(self.__getLastItemUpdate, request, pwd, request.postpath[0])
      d.addCallback(self.__getItem, request, pwd, request.postpath[0])

    # if URI is sth. like /[dbname]/res.partner/7/something,
    #  return 404
    else:    # len(request.postpath) > 1
      d.addCallback(self.__raiseAnError,
        NoChildResources("/" + '/'.join([self.dbname, self.model, request.postpath[0]])))

    d.addErrback(self.__cleanup, request)
    return NOT_DONE_YET

  def render_POST(self, request):
    hello()
    user = request.getUser()
    pwd = request.getPassword()

    # login to OpenERP
    proxyCommon = Proxy(self.openerpUrl + 'common')
    d = proxyCommon.callRemote('login', self.dbname, user, pwd)
    d.addCallback(self.__handleLoginAnswer)
    d.addCallback(self.__updateTypedesc, pwd)

    # if uri is sth. like /[dbname]/res.partner,
    #  POST creates an entry in this collection:
    if not request.postpath:
      d.addCallback(self.__addToCollection, request, pwd)

    # if URI is sth. like /[dbname]/res.partner/something,
    #  return 400, cannot POST here
    else:
      d.addCallback(self.__raiseAnError,
        PostNotPossible("/" + '/'.join([self.dbname, self.model, request.postpath[0]])))

    d.addErrback(self.__cleanup, request)
    return NOT_DONE_YET


class InvalidParameter(Exception):
  code = 400
  def __init__(self, param):
    self.param = param
  def __str__(self):
    return "Invalid parameter: "+str(self.param)

class PostNotPossible(Exception):
  code = 400
  def __init__(self, res):
    self.res = res
  def __str__(self):
    return "You cannot POST to "+str(self.res)

class NoChildResources(Exception):
  code = 404
  def __init__(self, res):
    self.res = res
  def __str__(self):
    return str(self.res) + " has no child resources"


if __name__ == "__main__":
  # read config
  config = ConfigParser.RawConfigParser()
  config.read('restful-openerp.cfg')
  openerpUrl = config.get("OpenERP", "url")
  try:
    port = config.getint("Proxy Settings", "port")
  except:
    port = 8068
  # go
  log.startLogging(sys.stdout)
  root = OpenErpDispatcher(openerpUrl)
  factory = Site(root)
  reactor.listenTCP(port, factory)
  reactor.run()
