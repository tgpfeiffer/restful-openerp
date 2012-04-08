#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser, datetime, dateutil.tz
from xml.sax.saxutils import escape as xmlescape

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import *
from twisted.internet import reactor, task
from twisted.python import log
from twisted.web.xmlrpc import Proxy

import pyatom

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
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'search', [])
    d.addCallback(self.__handleCollectionAnswer, request, uid, pwd)
    return d

  def __handleCollectionAnswer(self, val, request, uid, pwd):

    def createFeed(items, request):
      # build a feed
      # TODO: add the feed url; will currently break the test
      feed = pyatom.AtomFeed(title=self.model+" items",
                             id=str(request.URLPath()),
                             #feed_url=str(request.URLPath())
                             )
      for item in items:
        if item['user_id']:
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
      request.write(str(feed.to_string()))
      request.finish()

    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', val, ['name', '__last_update', 'user_id'])
    d.addCallback(createFeed, request)
    return d

  ### get __last_update of a collection item

  def __getLastItemUpdate(self, uid, request, pwd, modelId):
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

  ### list one particular item of a collection

  def __getItem(self, (uid, updateTime), request, pwd, modelId):
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId])
    d.addCallback(self.__handleItemAnswer, request, updateTime)
    return d

  def __handleItemAnswer(self, val, request, updateTime):
    # val should be a one-element-list with a dictionary describing the current object
    try:
      item = val[0]
    except IndexError, e:
      request.setResponseCode(404)
      request.write("No such resource.")
      request.finish()

    # set correct headers
    lastModified = localTimeStringToUtcDatetime(updateTime)
    request.setHeader("Last-Modified", httpdate(lastModified))
    request.setHeader("Content-Type", "application/atom+xml")
    # compose answer
    request.write('''<?xml version="1.0" encoding="utf-8"?>
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
       '/'.join(str(request.URLPath()).split("/")[:-1] + ["schema", self.model]),
       ))
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

  ### update the model information

  def __updateTypedesc(self, uid, pwd):
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
    self.desc = val
    return uid

  def __handleTypedescError(self, err, uid):
    # if an error appears while updating the type description
    return uid

  def __cleanup(self, err, request):
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
    else:
      request.setResponseCode(500)
      request.write("An error occured:\n"+e.faultCode)
    request.finish()

  ### HTTP request handling
    
  def render_GET(self, request):
    user = request.getUser()
    pwd = request.getPassword()

    # if uri is sth. like /[dbname]/res.partner,
    #  give a list of all objects in this collection:
    if not request.postpath:
      # login to OpenERP
      proxyCommon = Proxy(self.openerpUrl + 'common')
      d = proxyCommon.callRemote('login', self.dbname, user, pwd)
      d.addCallback(self.__updateTypedesc, pwd)
      d.addCallback(self.__getCollection, request, pwd)
      d.addErrback(self.__cleanup, request)
      return NOT_DONE_YET

    # if URI is sth. like /[dbname]/res.partner/7,
    #  list this particular item
    elif len(request.postpath) == 1:
      # login to OpenERP
      proxyCommon = Proxy(self.openerpUrl + 'common')
      d = proxyCommon.callRemote('login', self.dbname, user, pwd)
      d.addCallback(self.__updateTypedesc, pwd)
      d.addCallback(self.__getLastItemUpdate, request, pwd, request.postpath[0])
      d.addCallback(self.__getItem, request, pwd, request.postpath[0])
      d.addErrback(self.__cleanup, request)
      return NOT_DONE_YET

    # if URI is sth. like /[dbname]/res.partner/7/something,
    #  return 404
    else:    # len(request.postpath) > 1
      request.setResponseCode(404)
      return "/%s has no child resources" % ('/'.join([self.dbname, self.model, request.postpath[0]]))


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
