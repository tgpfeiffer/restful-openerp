#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

import sys, xmlrpclib, ConfigParser, datetime, dateutil.tz, inspect, re
from xml.sax.saxutils import escape as xmlescape

from lxml import etree

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import ErrorPage, Resource
from twisted.internet import reactor, task
from twisted.python import log
from twisted.web.xmlrpc import Proxy

import pyatom

def hello():
  """If you wanted, you could log some message from here to understand the
call stack a bit better..."""
  stack = inspect.stack()
  parent = stack[1][3]
  #print parent

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
  
  def __init__(self, openerpUrl):
    Resource.__init__(self)
    self.databases = {}
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
    self.models = {}
  
  # @override http://twistedmatrix.com/documents/10.0.0/api/twisted.web.resource.Resource.html#getChild
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

  def __updateDefaults(self, uid, pwd):
    hello()
    if not self.defaults:
      # update type description
      proxy = Proxy(self.openerpUrl + 'object')
      d = proxy.callRemote('execute', self.dbname, uid, pwd, self.model, 'default_get', self.desc.keys())
      d.addCallback(self.__handleDefaultsAnswer, uid)
      return d
    else:
      return uid

  def __handleDefaultsAnswer(self, val, uid):
    hello()
    log.msg("updating default values for "+self.model)
    self.defaults = val
    return uid

  def __getItemDefaults(self, uid, request, pwd):
    hello()
    # set correct headers
    request.setHeader("Content-Type", "application/atom+xml")
    # compose answer
    request.write(self.__mkDefaultXml(str(request.URLPath()), self.desc, self.defaults))
    request.finish()

  def __mkDefaultXml(self, path, desc, item):
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
  <%s xmlns="%s">
    <id />
''' % (self.model,
       path+"/defaults",
       datetime.datetime.utcnow().isoformat()[:-7]+'Z',
       path+"/defaults",
       'None',
       self.model.replace('.', '_'),
       '/'.join(path.split("/") + ["schema"]),
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
          key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]))
        )
      elif not value and fieldtype != "boolean":
        xml += ("    <%s type='%s' />\n" % (
          key,
          fieldtype)
        )
      # display URIs for many2one fields
      elif fieldtype == 'many2one':
        xml += ("    <%s type='%s' relation='%s'>\n      <link href='%s' />\n    </%s>\n" % (
          key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]),
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"], str(value)]),
          key)
        )
      # display URIs for *2many fields, wrapped by <item>
      elif fieldtype in ('one2many', 'many2many'):
        xml += ("    <%s type='%s' relation='%s'>%s</%s>\n" % (
          key,
          fieldtype,
          '/'.join(path.split("/")[:-1] + [self.desc[key]["relation"]]),
          ''.join(
            ['\n      <link href="' + '/'.join(path.split("/")[:-1] + [desc[key]["relation"], str(v)]) + '" />' for v in value]
          ) + '\n    ',
          key)
        )
      # for other fields, just output the data
      elif fieldtype == 'boolean':
        xml += ("    <%s type='%s'>%s</%s>\n" % (
          key,
          fieldtype,
          xmlescape(str(value and "True" or "False")),
          key)
        )
      else:
        xml += ("    <%s type='%s'>%s</%s>\n" % (
          key,
          fieldtype,
          xmlescape(str(value)),
          key)
        )
    xml += ("  </%s>\n  </content>\n</entry>" % self.model.replace('.', '_'))
    return xml

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
    except IndexError:
      request.setResponseCode(404)
      request.write("No such resource.")
      request.finish()
      return

    # set correct headers
    request.setHeader("Last-Modified", httpdate(lastModified))
    request.setHeader("Content-Type", "application/atom+xml")
    # compose answer
    path = str(request.URLPath())+"/"+str(item['id'])
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
''' % (item.has_key('name') and item['name'] or "None",
       path,
       lastModified.isoformat()[:-13]+'Z',
       path,
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
        if not value and fieldtype in ('many2one', 'one2many', 'many2many'):
          request.write("    <%s type='%s' relation='%s'><!-- %s --></%s>\n" % (
            key,
            fieldtype,
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"]]),
            value,
            key)
          )
        elif not value and fieldtype != "boolean":
          request.write("    <%s type='%s'><!-- %s --></%s>\n" % (
            key,
            fieldtype,
            value,
            key)
          )
        # display URIs for many2one fields
        elif fieldtype == 'many2one':
          request.write("    <%s type='%s' relation='%s'>\n      <link href='%s' />\n    </%s>\n" % (
            key,
            fieldtype,
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"]]),
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"], str(value[0])]),
            key)
          )
        # display URIs for *2many fields, wrapped by <item>
        elif fieldtype in ('one2many', 'many2many'):
          request.write("    <%s type='%s' relation='%s'>%s</%s>\n" % (
            key,
            fieldtype,
            '/'.join(str(request.URLPath()).split("/")[:-1] + [self.desc[key]["relation"]]),
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
    request.write("  </%s>\n" % self.model.replace('.', '_'))
    for button in self.workflowDesc:
      if button.attrib.has_key("name") and \
          (not item.has_key("state") or not button.attrib.has_key("states") or item["state"] in button.attrib['states'].split(",")) \
          and not self.__is_number(button.attrib["name"]):
        request.write("  <link rel='%s' href='%s' title='%s' />\n" % \
          (button.attrib['name'], path+"/"+button.attrib['name'], button.attrib['string']))
    request.write("  </content>\n</entry>")
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
    defaultDocRoot = etree.fromstring(self.__mkDefaultXml(str(request.URLPath()), self.desc, self.defaults), parser=parser)
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
    proxy = Proxy(self.openerpUrl + 'object')
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
    proxy = Proxy(self.openerpUrl + 'object')
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
    if currentAction.attrib.has_key("type"):
      raise NotImplementedError("don't know how to handle workflow '%s'" % workflow)
    proxy = Proxy(self.openerpUrl + 'object')
    d = proxy.callRemote('exec_workflow', self.dbname, uid, pwd, self.model, workflow, modelId)
    d.addCallback(self.__handleWorkflowAnswer, request, modelId, workflow)
    return d

  def __handleWorkflowAnswer(self, result, request, modelId, workflow):
    request.setResponseCode(204)
    loc = str(request.URLPath()) + "/" + str(modelId)
    request.setHeader("Location", loc)
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
      proxy = Proxy(self.openerpUrl + 'object')
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
      proxy = Proxy(self.openerpUrl + 'object')
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
        xml += ('\n    <%s><element name="link"><attribute name="href" /></element></%s>\n  ' % (elemName, elemName))
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
    request.setHeader("Content-Type", "text/plain")
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
    proxyCommon = Proxy(self.openerpUrl + 'common')
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
