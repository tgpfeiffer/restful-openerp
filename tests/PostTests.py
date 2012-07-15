#!/usr/bin/python
# -*- coding: utf-8 -*-

# (C) 2012 Tobias G. Pfeiffer <tgpfeiffer@web.de>

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3 as published by
# the Free Software Foundation.

from lxml import etree

from twisted.web.http_headers import Headers
from twisted.internet.defer import Deferred, DeferredList

import feedvalidator
from feedvalidator import compatibility
from feedvalidator.formatter.text_plain import Formatter

from tests import OpenErpProxyTest, PrinterClient

class PostResponseCodesTest(OpenErpProxyTest):

  def test_whenNoBasicAuthThen401(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/',
        Headers({}),
        None)
    return d.addCallback(self._checkResponseCode, 401)

  def test_whenAccessToRootResourceThen405(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 405)

  ## test collection

  def test_whenWrongAuthToProperCollectionThen403(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToNonExistingCollectionThen404(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partnerx',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 404)

  ## test resource

  def test_whenWrongAuthToProperResourceThen403(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/4',
        Headers({'Authorization': ['Basic %s' % 'bla:blub'.encode('base64')]}),
        None)
    return d.addCallback(self._checkResponseCode, 403)

  def test_whenAccessToProperResourceThen400(self):
    # TODO: make sure that we actually have an existing resource
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/4',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToInvalidResourceThen400(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToResourceChildThen400(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/4/abc',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToNonExistingResourceThen400(self):
    # TODO: make sure that we actually have an non-existing resource
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/-1',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  def test_whenAccessToAnotherNonExistingResourceThen400(self):
    d = self.agent.request(
        'POST',
        'http://localhost:8068/erptest/res.partner/100000000',
        Headers({'Authorization': ['Basic %s' % self.basic]}),
        None)
    return d.addCallback(self._checkResponseCode, 400)

  # NB. we do not have a test for "whenAccessToProperCollection" since
  #  this situation is much more difficult
