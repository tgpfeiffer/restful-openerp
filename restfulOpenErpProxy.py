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
      return ForbiddenResource("Use HTTP Basic Authentication to access resources.")
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
  """This is accessed when going to /{database}/{model}."""
  def __init__(self, openerpUrl, dbname, model):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    self.dbname = dbname
    self.model = model
    
  def render_GET(self, request):
    user = request.getUser()
    pwd = request.getPassword()
    try:
      sock_common = xmlrpclib.ServerProxy (self.openerpUrl + 'common')
      uid = sock_common.login(self.dbname, user, pwd)
      sock = xmlrpclib.ServerProxy(self.openerpUrl + 'object')
      ids = sock.execute(self.dbname, uid, pwd, self.model, 'search', [])
      return str(ids)+"\n"
    except xmlrpclib.Fault, e:
      if e.faultCode == "AccessDenied":
        request.setResponseCode(403)
        return "Bad credentials."
      else:
        request.setResponseCode(500)
        return "An error occured:\n"+str(e)


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
