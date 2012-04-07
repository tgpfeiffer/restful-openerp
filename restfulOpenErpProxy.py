#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import *
from twisted.internet import reactor, task
from twisted.python import log
from twisted.web.xmlrpc import Proxy


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
    d.addCallback(self.__handleCollectionAnswer, request)
    d.addErrback(self.__handleCollectionError, request)

  def __handleCollectionAnswer(self, val, request):
    #print "collection success", val
    request.write(str(val))
    request.finish()

  def __handleCollectionError(self, err, request):
    #print "collection error", err
    err.trap(xmlrpclib.Fault)
    e = err.value
    if e.faultCode == "AccessDenied":
      request.setResponseCode(403)
      request.write("Bad credentials.")
    else:
      request.setResponseCode(500)
      request.write("An error occured:\n"+e.faultCode)
    request.finish()

  ### list one particular item of a collection

  def __getItem(self, uid, request, pwd, modelId):
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId])
    d.addCallback(self.__handleItemAnswer, request)
    d.addErrback(self.__handleItemError, request)

  def __handleItemAnswer(self, val, request):
    #print "item success", val
    try:
      request.write(str(val[0]))
    except IndexError, e:
      request.setResponseCode(404)
      request.write("No such resource.")
    request.finish()

  def __handleItemError(self, err, request):
    #print "item error", err
    err.trap(xmlrpclib.Fault)
    e = err.value
    if e.faultCode == "AccessDenied":
      request.setResponseCode(403)
      request.write("Bad credentials.")
    elif e.faultCode.startswith("warning -- AccessError"):
      # the above results from a xmlrpclib problem: error message in faultCode
      request.setResponseCode(404)
      request.write("No such resource.")
    else:
      request.setResponseCode(500)
      request.write("An error occured:\n"+e.faultCode)
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
      return NOT_DONE_YET

    # if URI is sth. like /[dbname]/res.partner/7,
    #  list this particular item
    elif len(request.postpath) == 1:
      # login to OpenERP
      proxyCommon = Proxy(self.openerpUrl + 'common')
      d = proxyCommon.callRemote('login', self.dbname, user, pwd)
      d.addCallback(self.__updateTypedesc, pwd)
      d.addCallback(self.__getItem, request, pwd, request.postpath[0])
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
