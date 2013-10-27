#!/usr/bin/python
#-*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

# *restful-openerp* provides a RESTful HTTP endpoint for OpenERP, basically
# transforming incoming requests into corresponding XML-RPC calls to a
# configured OpenERP instance.  The main purpose is to allow HTTP caching
# of requests before they actually hit the backend by following REST design
# principles.  Therefore, *restful-openerp* allows to use OpenERP as a live
# data source for web shops etc.
#
# Many of the concepts that we tried to implement have been inspired by the
# [REST in Practice](http://restinpractice.com/book/) book.  Documentation
# can be built using one of the [docco](https://github.com/jashkenas/docco)
# derivatives.

import sys, xmlrpclib, ConfigParser, datetime, dateutil.tz, inspect, re
from xml.sax.saxutils import escape as xmlescape

from lxml import etree

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import ErrorPage, Resource
from twisted.internet import reactor, task
from twisted.python import log
from twisted.web.xmlrpc import Proxy

import pyatom


# Helpers
# -------
#
# We use the [Twisted](http://twistedmatrix.com/) framework both to listen
# for HTTP requests and issue the XML-RPC calls to the backend.  Twisted
# is an asynchronous framework using a callback mechanism that might make
# it hard to follow the control flow.  The `hello()` function can be used
# during debugging to see what functions are called when a request is
# processed.

def hello():
  """If you wanted, you could log some message from here to understand the
  call stack a bit better..."""
  stack = inspect.stack()
  parent = stack[1][3]
  #print parent

def localTimeStringToUtcDatetime(s):
  """Helper function to take a string like "2013-01-01 20:41:36.12345"
  representing a local time and use the information about the local
  timezone to create a datetime object in UTC time."""
  tz=dateutil.tz.tzlocal()
  utc=dateutil.tz.tzutc()
  t = datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S.%f') # this time is in local tz
  t_withtz = t.replace(tzinfo=tz)
  return t_withtz.astimezone(utc)

def httpdate(dt):
  """Helper function to return a string representation of a datetime
  object suitable for inclusion in a HTTP header."""
  return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

# `UnauthorizedPage` is a helper class to represent a 401 "Unauthorized"
# HTTP response.  This response will be used when there is no user/password
# Basic authentication information in the header.

class UnauthorizedPage(ErrorPage):
  def __init__(self):
    ErrorPage.__init__(self, 401, "Unauthorized", "Use HTTP Basic Authentication!")
  def render(self, request):
    r = ErrorPage.render(self, request)
    request.setHeader("WWW-Authenticate", 'Basic realm="OpenERP"')
    return r

def quietProxy(url):
  p = Proxy(url)
  p.queryFactory.noisy = False
  return p

# Dispatcher
# ----------
#
# This is the first class that is hit for an incoming request.  First, it
# ensures that we have a user/password set in the header.  Then it looks
# at the first component of the path, which is the name of the OpenERP
# database that we want to work with (like `myerp`).  It checks whether we
# have an corresponding instance of the `OpenErpDbResource` class cached
# in `self.databases` and creates one, if not.  Then, it passes the request
# on to that object by returning from the `getChild()` method.

class OpenErpDispatcher(Resource, object):
  
  def __init__(self, openerpUrl):
    Resource.__init__(self)
    self.databases = {}
    self.openerpUrl = openerpUrl
    log.msg("Server starting up with backend: " + self.openerpUrl)

  #@override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChildWithDefault
  def getChildWithDefault(self, pathElement, request):
    """Ensure that we have HTTP Basic Auth."""
    if not (request.getUser() and request.getPassword()):
      return UnauthorizedPage()
    else:
      return super(OpenErpDispatcher, self).getChildWithDefault(pathElement, request)
  
  #@override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChild
  def getChild(self, path, request):
    """Return a resource for the correct database."""
    if self.databases.has_key(path):
      return self.databases[path]
    else:
      log.msg("Creating resource for '%s' database." % path)
      self.databases[path] = OpenErpDbResource(self.openerpUrl, path)
      return self.databases[path]


# Database Resource
# -----------------
#
# This is the class that is used after the `OpenErpDispatcher` when processing
# a request.  Since there is no result associated to a URL with just a first
# component, the only action of this class is to pass on the request handling
# to a corresponding instance of `OpenErpModelResource` based on the second
# component, the model that we want to access (like `res.partner`). It checks
# whether we have such an instance cached in `self.models` and creates one,
# if not.  Then, it passes the request on to that object by returning from
# the `getChild()` method.

class OpenErpDbResource(Resource):

  """This is accessed when going to /{database}."""
  def __init__(self, openerpUrl, dbname):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    self.dbname = dbname
    self.models = {}
  
  #@override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChild
  def getChild(self, path, request):
    if self.models.has_key(path):
      return self.models[path]
    else:
      log.msg("Creating resource for '%s' model." % path)
      self.models[path] = OpenErpModelResource(self.openerpUrl, self.dbname, path)
      return self.models[path]


class OpenErpModelResource(Resource):
  isLeaf = True

  """This is accessed when going to /{database}/{model}."""
  def __init__(self, openerpUrl, dbname, model):
    Resource.__init__(self)
    self.openerpUrl = openerpUrl
    self.dbname = dbname
    self.model = model
    self.desc = {}
    self.workflowDesc = []
    self.defaults = {}
    # clear self.desc and self.default every two hours
    self.cleanUpTask = task.LoopingCall(self.clearCachedValues)
    self.cleanUpTask.start(60 * 60 * 2)

  def clearCachedValues(self):
    log.msg("clearing schema/default cache for "+self.model)
    self.desc = {}
    self.defaults = {}

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
        if len(vals) == 1:
          try:
            val = int(vals[0])
          except:
            val = vals[0]
          params.append((key, '=', val))
        else:
          newVals = []
          for v in vals:
            try:
              val = int(v)
            except:
              val = v
            newVals.append(v)
          params.append((key, 'in', tuple(newVals)))
    proxy = quietProxy(self.openerpUrl + 'object')
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
        if not item['name']:
          item['name'] = "None"
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
      request.setHeader("Content-Type", "application/atom+xml; charset=utf-8")
      request.write(str(feed.to_string().encode('utf-8')))
      request.finish()

    proxy = quietProxy(self.openerpUrl + 'object')
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
    proxy = quietProxy(self.openerpUrl + 'object')
    def handleLastItemUpdateAnswer(updateAnswer):
      if not updateAnswer:
        raise NotFound(str(request.URLPath()))
      return (uid, updateAnswer[0]['__last_update'])
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], ['__last_update'])
    d.addCallback(handleLastItemUpdateAnswer)
    return d

  ### list the default values for an item

  def __updateDefaults(self, uid, pwd):
    hello()
    if not uid in self.defaults:
      # update type description
      proxy = quietProxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'default_get', self.desc.keys(), {})
      d.addCallback(self.__handleDefaultsAnswer, uid)
      return d
    else:
      return uid

  def __handleDefaultsAnswer(self, val, uid):
    hello()
    log.msg("updating default values (uid=" + str(uid) + ") for " + self.model)
    self.defaults[uid] = val
    return uid

  def __getItemDefaults(self, uid, request, pwd):
    hello()
    # set correct headers
    request.setHeader("Content-Type", "application/atom+xml; charset=utf-8")
    # compose answer
    request.write(self.__mkDefaultXml(str(request.URLPath()), self.desc, self.defaults[uid]))
    request.finish()

  def __mkDefaultXml(self, path, desc, item):
    ns = "".join([word[0] for word in self.model.split('.')])
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title type="text">Defaults for %s</title>
  <id>%s</id>
  <updated>%s</updated>
  <link href="%s" rel="self" />
  <author>
    <name>%s</name>
  </author>
  <content type="application/vnd.openerp+xml">
  <%s xmlns:%s="%s">
    <%s:id />
''' % (self.model,
       path+"/defaults",
       datetime.datetime.utcnow().isoformat()[:-7]+'Z',
       path+"/defaults",
       'None',
       ns + ":" + self.model.replace('.', '_'),
       ns,
       '/'.join(path.split("/") + ["schema"]),
       ns
       )
    # loop over the fields of the current object
    for key in desc.iterkeys():
      value = item.has_key(key) and item[key] or ""
      # key is the name of the field, value is the content,
      #  e.g. key="email", value="me@privacy.net"
      fieldtype = desc[key]['type']
      # if we have an empty field, we display a closed tag
      #  (except if this is a boolean field)
      if not value and fieldtype in ('many2one', 'one2many', 'many2many'):
        xml += ("    <%s type='%s' relation='%s' />\n" % (
          ns + ":" + key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]))
        )
      elif not value and fieldtype != "boolean":
        xml += ("    <%s type='%s' />\n" % (
          ns + ":" + key,
          fieldtype)
        )
      # display URIs for many2one fields
      elif fieldtype == 'many2one':
        xml += ("    <%s type='%s' relation='%s'>\n      <link href='%s' />\n    </%s>\n" % (
          ns + ":" + key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]),
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"], str(value)]),
          ns + ":" + key)
        )
      # display URIs for *2many fields, wrapped by <item>
      elif fieldtype in ('one2many', 'many2many'):
        xml += ("    <%s type='%s' relation='%s'>%s</%s>\n" % (
          ns + ":" + key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]),
          ''.join(
            ['\n      <link href="' + '/'.join(path.split("/")[:-1] + [desc[key]["relation"], str(v)]) + '" />' for v in value]
          ) + '\n    ',
          ns + ":" + key)
        )
      # for other fields, just output the data
      elif fieldtype == 'boolean':
        xml += ("    <%s type='%s'>%s</%s>\n" % (
          ns + ":" + key,
          fieldtype,
          xmlescape(str(value and "True" or "False")),
          ns + ":" + key)
        )
      else:
        xml += ("    <%s type='%s'>%s</%s>\n" % (
          ns + ":" + key,
          fieldtype,
          xmlescape(str(value)),
          ns + ":" + key)
        )
    xml += ("  </%s>\n  </content>\n</entry>" % (ns + ":" + self.model.replace('.', '_')))
    return xml

  ### list one particular item of a collection

  def getParamsFromRequest(self, request):
    params = {}
    for key, vals in request.args.iteritems():
      try:
        val = int(vals[0])
      except:
        val = vals[0]
      params[key] = val
      if key == "active_id":
        params["active_ids"] = [val]
    return params

  def __getItem(self, (uid, updateTime), request, pwd, modelId):
    hello()
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    # we add 'context' parameters, like 'lang' or 'tz'
    params = self.getParamsFromRequest(request)
    # issue the request
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], [], params)
    d.addCallback(self.__handleItemAnswer, request, localTimeStringToUtcDatetime(updateTime))
    return d

  def __mkItemXml(self, ns, schema, basePath, path, lastModified, item):
    result = ""
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
  <%s xmlns:%s="%s">
''' % (xmlescape(unicode(item.has_key('name') and item['name'] or "None")),
       path,
       lastModified.isoformat()[:-13]+'Z',
       path,
       'None', # TODO: insert author, if present
       ns + ":" + self.model.replace('.', '_'),
       ns,
       schema,
       )
    result += xmlHead.encode('utf-8')
    # loop over the fields of the current object
    for key, value in item.iteritems():
      # key is the name of the field, value is the content,
      #  e.g. key="email", value="me@privacy.net"
      if self.desc.has_key(key):
        fieldtype = self.desc[key]['type']
        # if we have an empty field, we display a closed tag
        #  (except if this is a boolean field)
        if not value and fieldtype in ('many2one', 'one2many', 'many2many'):
          result += "    <%s type='%s' relation='%s'><!-- %s --></%s>\n" % (
            ns + ":" + key,
            fieldtype,
            '/'.join(basePath.split("/")[:-1] + [self.desc[key]["relation"]]),
            value,
            ns + ":" + key)
        elif not value and fieldtype != "boolean":
          result += "    <%s type='%s'><!-- %s --></%s>\n" % (
            ns + ":" + key,
            fieldtype,
            value,
            ns + ":" + key)
        # display URIs for many2one fields
        elif fieldtype == 'many2one':
          result += "    <%s type='%s' relation='%s'>\n      <link href='%s' />\n    </%s>\n" % (
            ns + ":" + key,
            fieldtype,
            '/'.join(basePath.split("/")[:-1] + [self.desc[key]["relation"]]),
            '/'.join(basePath.split("/")[:-1] + [self.desc[key]["relation"], str(value[0])]),
            ns + ":" + key)
        # display URIs for *2many fields, wrapped by <item>
        elif fieldtype in ('one2many', 'many2many'):
          result += "    <%s type='%s' relation='%s'>%s</%s>\n" % (
            ns + ":" + key,
            fieldtype,
            '/'.join(basePath.split("/")[:-1] + [self.desc[key]["relation"]]),
            ''.join(
              ['\n      <link href="' + '/'.join(basePath.split("/")[:-1] + [self.desc[key]["relation"], str(v)]) + '" />' for v in value]
            ) + '\n    ',
            ns + ":" + key)
        # for other fields, just output the data
        else:
          result += "    <%s type='%s'>%s</%s>\n" % (
            ns + ":" + key,
            fieldtype,
            xmlescape(unicode(value).encode('utf-8')),
            ns + ":" + key)
      else: # no type given or no self.desc present
        result += "    <%s>%s</%s>\n" % (
          ns + ":" + key,
          xmlescape(unicode(value).encode('utf-8')),
          ns + ":" + key)
    result += "  </%s>\n" % (ns + ":" + self.model.replace('.', '_'))
    for button in self.workflowDesc:
      if button.attrib.has_key("name") and \
          (not item.has_key("state") or not button.attrib.has_key("states") or item["state"] in button.attrib['states'].split(",")) \
          and not self.__is_number(button.attrib["name"]):
        result += "  <link rel='%s' href='%s' title='%s' />\n" % \
          (button.attrib['name'], path+"/"+button.attrib['name'], button.attrib['string'])
    result += "  </content>\n</entry>"
    return result

  def __handleItemAnswer(self, val, request, lastModified):
    hello()
    # val should be a one-element-list with a dictionary describing the current object
    try:
      item = val[0]
    except IndexError:
      request.setResponseCode(404)
      request.write("No such resource.")
      request.finish()
      return

    # set correct headers
    request.setHeader("Last-Modified", httpdate(lastModified))
    request.setHeader("Content-Type", "application/atom+xml; charset=utf-8")
    # compose answer
    ns = "".join([word[0] for word in self.model.split('.')])
    basepath = str(request.URLPath())
    path = basepath+"/"+str(item['id'])
    s = self.__mkItemXml(ns, basepath + "/schema", basepath, path, lastModified, item)
    request.write(s)
    request.finish()

  def __is_number(self, n):
    try:
      x = int(n)
      return True
    except:
      return False

  ### handle inserts into collection

  def __addToCollection(self, uid, request, pwd):
    """This is called after successful login to add an items
    to a certain collection, e.g. a new res.partner."""
    hello()
    if not self.desc:
      raise xmlrpclib.Fault("warning -- Object Error", "no such collection")
    # check whether we got well-formed XML
    parser = etree.XMLParser(remove_comments=True)
    try:
      doc = etree.fromstring(request.content.read(), parser=parser)
    except Exception as e:
      request.setResponseCode(400)
      request.write("malformed XML: "+str(e))
      request.finish()
      return
    # check whether we got valid XML with the given schema
    ns = str(request.URLPath()) + "/schema"
    schemaxml = self.__desc2relaxNG(str(request.URLPath()), self.desc)
    schema = etree.fromstring(schemaxml)
    relaxng = etree.RelaxNG(schema)
    # to validate doc, we need to set "id" to a numeric value
    try:
      doc.find("{%s}id" % ns).text = "-1"
    except:
      pass
    if not relaxng.validate(doc):
      request.setResponseCode(400)
      err = relaxng.error_log
      request.write("invalid XML:\n"+str(err))
      request.finish()
      return
    # get default values for this model
    defaultDocRoot = etree.fromstring(self.__mkDefaultXml(str(request.URLPath()), self.desc, self.defaults[uid]), parser=parser)
    defaultDoc = defaultDocRoot.find("{http://www.w3.org/2005/Atom}content").find("{%s}%s" % (ns, self.model.replace(".", "_")))
    stripNsRe = re.compile(r'^{%s}(.+)$' % ns)
    whitespaceRe = re.compile(r'\s+')
    # collect all fields with non-default values
    fields = {}
    for c in doc.getchildren():
      if c.tag == "{%s}id" % ns or c.tag == "{%s}create_date" % ns:
        # will not update id or create_date
        continue
      elif whitespaceRe.sub(" ", etree.tostring(c, pretty_print=True).strip()) == whitespaceRe.sub(" ", etree.tostring(defaultDoc.find(c.tag), pretty_print=True).strip()):
        # c has default value
        continue
      # we can assume the regex will match due to validation beforehand
      tagname = stripNsRe.search(c.tag).group(1)
      if c.attrib["type"] in ("char", "selection", "text", "datetime"):
        fields[tagname] = c.text
      elif c.attrib["type"] == "float":
        fields[tagname] = float(c.text)
      elif c.attrib["type"] == "integer":
        fields[tagname] = int(c.text)
      elif c.attrib["type"] == "boolean":
        fields[tagname] = (c.text == "True")
      elif c.attrib["type"] == "many2one":
        assert c.attrib['relation'] == defaultDoc.find(c.tag).attrib['relation']
        uris = [link.attrib['href'] for link in c.getchildren()]
        ids = [int(u[u.rfind('/')+1:]) for u in uris if u.startswith(c.attrib['relation'])]
        if ids:
          fields[tagname] = ids[0]
      elif c.attrib["type"] in ("many2many", "one2many"):
        assert c.attrib['relation'] == defaultDoc.find(c.tag).attrib['relation']
        uris = [link.attrib['href'] for link in c.getchildren()]
        ids = [int(u[u.rfind('/')+1:]) for u in uris if u.startswith(c.attrib['relation'])]
        if ids:
          fields[tagname] = [(6, 0, ids)]
      else:
        # TODO: date, many2one (we can't really set many2many and one2many here, can we?)
        raise NotImplementedError("don't know how to handle element "+c.tag+" of type "+c.attrib["type"])
    # compose the XML-RPC call from them
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'create', fields)
    d.addCallback(self.__handleAddCollectionAnswer, request)
    return d

  def __handleAddCollectionAnswer(self, object_id, request):
    hello()
    loc = str(request.URLPath()) + "/" + str(object_id)
    request.setResponseCode(201)
    request.setHeader("Location", loc)
    request.finish()

  ### handle workflows

  def __prepareWorkflow(self, uid, request, pwd, modelId, workflow):
    hello()
    modelId = int(modelId)
    # first, get information about the item
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], [])
    d.addCallback(self.__executeWorkflow, uid, request, pwd, modelId, workflow)
    return d

  def __executeWorkflow(self, val, uid, request, pwd, modelId, workflow):
    hello()
    # val should be a one-element-list with a dictionary describing the current object
    try:
      item = val[0]
    except IndexError:
      request.setResponseCode(404)
      request.write("No such resource.")
      request.finish()
      return
    # also, the given workflow should be valid for the current state
    for button in self.workflowDesc:
      if button.attrib.has_key("name") and \
          (not item.has_key("state") or item["state"] in button.attrib['states'].split(",")) \
          and not self.__is_number(button.attrib["name"]) and workflow == button.attrib['name']:
        currentAction = button
        break
    else:
      request.setResponseCode(400)
      request.write("Workflow '%s' not allowed in state '%s'." % \
        (workflow, (item.has_key("state") and item["state"]) or ''))
      request.finish()
      return
    # here, the workflow is allowed for the current object
    if currentAction.attrib.has_key("type") and currentAction.attrib['type'] == "object":
      # get a URL from the POST body and extract model and id
      myPath = str(request.URLPath())
      objRe = re.compile(myPath[:myPath.find(self.model)] + r'(.+)/([0-9]+)$')
      body = request.content.read()
      match = objRe.match(body)
      if not match:
        raise NotImplementedError("don't know how to handle input '%s' for workflow '%s'" % (body, workflow))
      # set parameters fro request
      params = {"active_model": match.group(1), "active_id": int(match.group(2)), "active_ids": [int(match.group(2))]}
      proxy = quietProxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, workflow, [modelId], params)
      d.addCallback(self.__handleWorkflowAnswer, request, modelId, workflow)
      return d
    elif currentAction.attrib.has_key("type"):
      raise NotImplementedError("don't know how to handle workflow '%s'" % workflow)
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('exec_workflow', self.dbname, uid, pwd, self.model, workflow, modelId)
    d.addCallback(self.__handleWorkflowAnswer, request, modelId, workflow)
    return d

  def __handleWorkflowAnswer(self, result, request, modelId, workflow):
    request.setResponseCode(204)
    loc = str(request.URLPath()) + "/" + str(modelId)
    request.setHeader("Location", loc)
    request.finish()

  ### handle updates

  def __getItemForUpdate(self, (uid, updateTime), request, pwd, modelId):
    hello()
    # make sure we're dealing with an integer id
    try:
      modelId = int(modelId)
    except:
      modelId = -1
    # we add 'context' parameters, like 'lang' or 'tz'
    params = self.getParamsFromRequest(request)
    # issue the request
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'read', [modelId], [], params)
    d.addCallback(self.__updateItem, uid, pwd, request, localTimeStringToUtcDatetime(updateTime))
    return d

  def __updateItem(self, old, uid, pwd, request, lastModified):
    """This is called after successful login to add an items
    to a certain collection, e.g. a new res.partner."""
    hello()
    if not self.desc:
      raise xmlrpclib.Fault("warning -- Object Error", "no such collection")
    # check whether we got well-formed XML
    parser = etree.XMLParser(remove_comments=True)
    try:
      doc = etree.fromstring(request.content.read(), parser=parser)
    except Exception as e:
      request.setResponseCode(400)
      request.write("malformed XML: "+str(e))
      request.finish()
      return
    # check whether we got valid XML with the given schema
    ns = str(request.URLPath()) + "/schema"
    schemaxml = self.__desc2relaxNG(str(request.URLPath()), self.desc)
    schema = etree.fromstring(schemaxml)
    relaxng = etree.RelaxNG(schema)
    # try to validate object
    if not relaxng.validate(doc):
      request.setResponseCode(400)
      err = relaxng.error_log
      request.write("invalid XML:\n"+str(err))
      request.finish()
      return
    # compose old values for this object
    xmlns = "".join([word[0] for word in self.model.split('.')])
    basepath = str(request.URLPath())
    path = basepath+"/"+str(old[0]['id'])
    s = self.__mkItemXml(xmlns, basepath + "/schema", basepath, path, lastModified, old[0])
    oldDocRoot = etree.fromstring(s, parser=parser)
    oldDoc = oldDocRoot.find("{http://www.w3.org/2005/Atom}content").find("{%s}%s" % (ns, self.model.replace(".", "_")))
    stripNsRe = re.compile(r'^{%s}(.+)$' % ns)
    whitespaceRe = re.compile(r'\s+')
    def isEquivalentXml(a, b):
      wsNormalizedA = whitespaceRe.sub(" ", etree.tostring(a, pretty_print=True).strip())
      wsNormalizedB = whitespaceRe.sub(" ", etree.tostring(b, pretty_print=True).strip())
      if wsNormalizedA == wsNormalizedB:
        return True
      elif a.attrib["type"] in ("char", "selection", "text", "datetime",
        "float", "integer", "boolean") and a.attrib["type"] == b.attrib["type"]:
        return a.text == b.text
      else:
        return False
    # collect all fields with new values
    fields = {}
    for c in doc.getchildren():
      if c.tag == "{%s}id" % ns or c.tag == "{%s}create_date" % ns:
        # will not update id or create_date
        continue
      elif isEquivalentXml(c, oldDoc.find(c.tag)):
        # c has old value
        continue
      # we can assume the regex will match due to validation beforehand
      tagname = stripNsRe.search(c.tag).group(1)
      if c.attrib["type"] in ("char", "selection", "text", "datetime"):
        fields[tagname] = c.text or ""
      elif c.attrib["type"] == "float":
        fields[tagname] = float(c.text)
      elif c.attrib["type"] == "integer":
        fields[tagname] = int(c.text)
      elif c.attrib["type"] == "boolean":
        fields[tagname] = (c.text == "True")
      elif c.attrib["type"] == "many2one":
        assert c.attrib['relation'] == oldDoc.find(c.tag).attrib['relation']
        oldUris = [link.attrib['href'] for link in oldDoc.find(c.tag).getchildren()]
        uris = [link.attrib['href'] for link in c.getchildren()]
        ids = [int(u[u.rfind('/')+1:]) for u in uris if u.startswith(c.attrib['relation'])]
        if ids and oldUris != uris:
          fields[tagname] = ids[0]
      elif c.attrib["type"] in ("many2many", "one2many"):
        assert c.attrib['relation'] == oldDoc.find(c.tag).attrib['relation']
        oldUris = [link.attrib['href'] for link in oldDoc.find(c.tag).getchildren()]
        uris = [link.attrib['href'] for link in c.getchildren()]
        ids = [int(u[u.rfind('/')+1:]) for u in uris if u.startswith(c.attrib['relation'])]
        if ids and oldUris != uris:
          fields[tagname] = [(6, 0, ids)]
      else:
        # TODO: date
        raise NotImplementedError("don't know how to handle element "+c.tag+" of type "+c.attrib["type"])
    # compose the XML-RPC call from them
    proxy = quietProxy(self.openerpUrl + 'object')
    d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'write', [old[0]['id']], fields)
    d.addCallback(self.__handleUpdateItemAnswer, request)
    return d

  def __handleUpdateItemAnswer(self, object_id, request):
    hello()
    request.setResponseCode(204)
    request.finish()

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
      proxy = quietProxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'fields_get', [])
      d.addCallback(self.__handleTypedescAnswer, uid)
      d.addErrback(self.__handleTypedescError, uid)
      return d
    else:
      return uid

  def __handleTypedescAnswer(self, val, uid):
    hello()
    log.msg("updating schema for "+self.model)
    if val.has_key("id"):
      del val["id"]
    self.desc = val
    return uid

  def __handleTypedescError(self, err, uid):
    hello()
    # if an error appears while updating the type description
    return uid

  def __updateWorkflowDesc(self, uid, pwd):
    hello()
    if not self.workflowDesc:
      # update type description
      proxy = quietProxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'fields_view_get', [])
      d.addCallback(self.__handleWorkflowDescAnswer, uid)
      d.addErrback(self.__handleWorkflowDescError, uid)
      return d
    else:
      return uid

  def __handleWorkflowDescAnswer(self, val, uid):
    hello()
    log.msg("updating workflow description for "+self.model)
    self.workflowDesc = etree.fromstring(val['arch']).findall(".//button")
    return uid

  def __handleWorkflowDescError(self, err, uid):
    hello()
    # if an error appears while updating the type description
    return uid

  def __desc2relaxNG(self, path, desc):
    ns = path + "/schema"
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<element name="%s" xmlns="http://relaxng.org/ns/structure/1.0" datatypeLibrary="http://www.w3.org/2001/XMLSchema-datatypes" ns="%s">
<interleave>
  <element name="id"><data type="decimal" /></element>
''' % (self.model.replace(".", "_"), ns)
    for key, val in desc.iteritems():
      fieldtype = val['type']
      required = val.has_key('required') and val['required'] or False
      xml += ('  <element name="%s">\n    <attribute name="type" />' % key)
      if fieldtype in ('many2one', 'many2many', 'one2many'):
        xml += '\n    <attribute name="relation" />'
      if fieldtype in ('many2many', 'one2many'):
        elemName = required and "oneOrMore" or "zeroOrMore"
        xml += ('\n    <%s><element name="link" ns="http://www.w3.org/2005/Atom"><attribute name="href" /></element></%s>\n  ' % (elemName, elemName))
      else:
        output = "\n    "
        # select the correct field type
        if fieldtype == "many2one":
          s = '<element name="link" ns="http://www.w3.org/2005/Atom"><attribute name="href" /></element>'
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
        xml += (output+'\n  ')
      xml += '</element>\n'
    xml += '</interleave>\n</element>'
    return xml

  def __getSchema(self, uid, request):
    hello()
    if not self.desc:
      request.setResponseCode(404)
      request.write("Schema description not found")
      request.finish()
      return
    else:
      request.write(self.__desc2relaxNG(str(request.URLPath()), self.desc))
      request.finish()

  ### error handling

  def __cleanup(self, err, request):
    hello()
    log.msg("cleanup: "+str(err))
    request.setHeader("Content-Type", "text/plain; charset=utf-8")
    e = err.value
    if err.check(xmlrpclib.Fault):
      if e.faultCode == "AccessDenied":
        request.setResponseCode(403)
        request.write("Bad credentials.")
      elif e.faultCode.startswith("warning -- AccessError") or e.faultCode.startswith("warning -- ZugrifffFehler"):
        # oh good, OpenERP spelling goodness...
        request.setResponseCode(404)
        request.write("No such resource.")
      elif e.faultCode.startswith("warning -- Object Error"):
        request.setResponseCode(404)
        request.write("No such collection.")
      else:
        request.setResponseCode(500)
        request.write("An XML-RPC error occured:\n"+e.faultCode.encode("utf-8"))
    elif e.__class__ in (InvalidParameter, PostNotPossible, PutNotPossible, NoChildResources, NotFound):
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
    proxyCommon = quietProxy(self.openerpUrl + 'common')
    d = proxyCommon.callRemote('login', self.dbname, user, pwd)
    d.addCallback(self.__handleLoginAnswer)
    d.addCallback(self.__updateTypedesc, pwd)
    d.addCallback(self.__updateWorkflowDesc, pwd)
    d.addCallback(self.__updateDefaults, pwd)

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
    proxyCommon = quietProxy(self.openerpUrl + 'common')
    d = proxyCommon.callRemote('login', self.dbname, user, pwd)
    d.addCallback(self.__handleLoginAnswer)
    d.addCallback(self.__updateTypedesc, pwd)
    d.addCallback(self.__updateWorkflowDesc, pwd)
    d.addCallback(self.__updateDefaults, pwd)

    # if uri is sth. like /[dbname]/res.partner,
    #  POST creates an entry in this collection:
    if not request.postpath:
      d.addCallback(self.__addToCollection, request, pwd)

    # if uri is sth. like /[dbname]/res.partner/27/something,
    #  POST executes a workflow on this object
    elif len(request.postpath) == 2 and self.__is_number(request.postpath[0]):
      d.addCallback(self.__prepareWorkflow, request, pwd, *request.postpath)

    # if URI is sth. like /[dbname]/res.partner/something,
    #  return 400, cannot POST here
    else:
      d.addCallback(self.__raiseAnError,
        PostNotPossible("/" + '/'.join([self.dbname, self.model, request.postpath[0]])))

    d.addErrback(self.__cleanup, request)
    return NOT_DONE_YET

  def render_PUT(self, request):
    hello()
    user = request.getUser()
    pwd = request.getPassword()

    # login to OpenERP
    proxyCommon = quietProxy(self.openerpUrl + 'common')
    d = proxyCommon.callRemote('login', self.dbname, user, pwd)
    d.addCallback(self.__handleLoginAnswer)
    d.addCallback(self.__updateTypedesc, pwd)
    d.addCallback(self.__updateWorkflowDesc, pwd)
    d.addCallback(self.__updateDefaults, pwd)

    # if uri is sth. like /[dbname]/res.partner/27,
    #  PUT updates this object
    if len(request.postpath) == 1 and self.__is_number(request.postpath[0]):
      d.addCallback(self.__getLastItemUpdate, request, pwd, request.postpath[0])
      d.addCallback(self.__getItemForUpdate, request, pwd, request.postpath[0])

    # if URI looks different, return 400, cannot PUT here
    else:
      d.addCallback(self.__raiseAnError,
        PutNotPossible(str(request.URLPath()) + ''.join(['/'+r for r in request.postpath])))

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

class PutNotPossible(Exception):
  code = 400
  def __init__(self, res):
    self.res = res
  def __str__(self):
    return "You cannot PUT to "+str(self.res)

class NoChildResources(Exception):
  code = 404
  def __init__(self, res):
    self.res = res
  def __str__(self):
    return str(self.res) + " has no child resources"

class NotFound(Exception):
  code = 404
  def __init__(self, res):
    self.res = res
  def __str__(self):
    return str(self.res) + " was not found"


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
