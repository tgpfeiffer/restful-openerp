#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import os, sys, xmlrpclib, ConfigParser

from twisted.web.server import Site
from twisted.web.resource import *
from twisted.internet import reactor, task
from twisted.python import log


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
    
  def render_GET(self, request):
    user = request.getUser()
    pwd = request.getPassword()

    if not request.postpath:
      # give a list of all resources
      try:
        sock_common = xmlrpclib.ServerProxy (self.openerpUrl + 'common')
        uid = sock_common.login(self.dbname, user, pwd)
        sock = xmlrpclib.ServerProxy(self.openerpUrl + 'object')
        ids = sock.execute(self.dbname, uid, pwd, self.model, 'search', [])
        # TODO: return list of URIs
        return str(ids)+"\n"
      except xmlrpclib.Fault, e:
        if e.faultCode == "AccessDenied":
          request.setResponseCode(403)
          return "Bad credentials."
        else:
          request.setResponseCode(500)
          return "An error occured:\n"+e.faultCode

    elif len(request.postpath) == 1:
      # give info about the resource with the given ID
      try:
        # make sure we're dealing with an integer id
        modelId = int(request.postpath[0])
      except:
        request.setResponseCode(404)
        return "No such resource."
      # read resource from OpenERP
      try:
        sock_common = xmlrpclib.ServerProxy (self.openerpUrl + 'common')
        uid = sock_common.login(self.dbname, user, pwd)
        sock = xmlrpclib.ServerProxy(self.openerpUrl + 'object')
        data = sock.execute(self.dbname, uid, pwd, self.model, 'read', [modelId])[0]
        return str(data)
      except xmlrpclib.Fault, e:
        if e.faultCode == "AccessDenied":
          request.setResponseCode(403)
          return "Access denied."
        elif e.faultCode.startswith("warning -- AccessError"):
          # the above results from a xmlrpclib problem: error message in faultCode
          request.setResponseCode(404)
          return "No such resource."
        else:
          request.setResponseCode(500)
          return "An error occured:\n"+e.faultCode
      except IndexError, e:
        request.setResponseCode(404)
        return "No such resource."

    else:    # len(request.postpath) > 1
      # this doesn't make sense
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
