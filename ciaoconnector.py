import os, sys, logging
import json, hashlib
from subprocess import check_call

import settings
from utils import *

class CiaoConnector(object):
	def __init__(self, name, conf, registered = False):
		self.name = name
		self.registered = registered
		self.logger = logging.getLogger("ciao.connector." + self.name)
		self.load_conf(conf)

		#interactions stash
		self.stash = {}

		#list of requests handled with two FIFO queues
		# in - OUTSIDE-IN (connectors -> MCU)
		# out - INSIDE-OUT (MCU -> connectors)
		self.fifo = { "in": [], "out": [] }

	def load_conf(self, conf):
		#TODO
		# we must provide conf validation (to prevent typos or missing params)
		# type can be:
		#  managed - started/stopped from ciao
		#  standalone - processes with their own "lives" that connect to ciao if available
		self.type = conf['type']
		if self.type == "managed":
			self.managed_start = conf['commands']['start']
			self.managed_stop = conf['commands']['stop']

		if "implements" in conf:
			self.implements = conf['implements']

	def start(self):
		self.logger.info("Received start command")
		if self.type == "managed":
			#if type is managed we have to start/stop connector "manually"
			##out = check_output(self.managed_start) requires python >= 2.7
			##self.debug("Start output: %s" % out)
			try:
				check_call(self.managed_start)
			except Exception, e:
				self.logger.error("Exception during %s start: %s" % (self.name, e))

	def stop(self):
		self.logger.info("Received stop commands")
		if self.type == "managed":
			##out = check_output(self.managed_stop) requires python >= 2.7
			##self.debug("Stop output: %s" % out)
			try:
				check_call(self.managed_stop)
			except Exception, e:
				self.logger.error("Exception during %s stop: %s" % (self.name, e))

	def is_registered(self):
		return self.registered

	def register(self):
		#if already registered we should return false (avoiding duplication)
		self.registered = True

	def unregister(self):
		self.registered = False

	# get element (hash) from stash "destination"
	def stash_get(self, destination):
		#TODO
		# probably we should remove elements from stash (other than from fifo)
		# if destination out and type response we should remove the original read too?
		if len(self.fifo[destination]) > 0:
			checksum = self.fifo[destination].pop(0)
			return checksum, self.stash[checksum]
		return False, False

	# put element (hash) identified by "checksum" into stash "destination"
	# type: out|result|response
	def stash_put(self, destination, checksum, element):
		self.stash[checksum] = element
		self.fifo[destination].append(checksum)
		return

	def has_result(self, checksum):
		return checksum in self.stash and "result" in self.stash[checksum]

	def get_result(self, checksum):
		return self.stash[checksum]["result"]

	def run(self, short_action, command):
		#retrieve real action value from short one (e.g. "r" => "read" )
		#action = settings.allowed_actions[short_action]['map']
		action = settings.actions_map[short_action]

		if not self.is_registered():
			self.logger.warning("Connector %s not yet registered" % self.name)
			out(0, "no_connector")
		elif not action in self.implements:
			self.logger.warning("Connector %s does not implement %s" % (self.name, action))
			out(0, "no_action")
		else:
			required_params = self.implements[action]['params']
			params = command.split(";", required_params)
			#TODO
			# after split we could check if len(params) match expected required_params value

			#action from the "world" to MCU
			if self.implements[action]['direction'] == 'in':
				pos, entry = self.stash_get("in")
				if pos:
					out(1, pos, entry["data"])
				else:
					out(0, "no_message")

			#action from MCU to the "world"
			elif self.implements[action]['direction'] == 'out':
				message = params[required_params - 1]
				checksum = get_checksum(message, False)

				data = unserialize(message, False)
				if action == "writeresponse":
					result = {
						"type": "response",
						# checksum of read interaction we are responding to
						# [0]connector,[1]action,[2]checksum (fixed positions in writeresponse)
						"source_checksum": params[2],
						"data": data
					}
				else:
					result = {
						"type": "out",
						"data": data
					}
				self.stash_put("out", checksum, result)
				out(1, "done")

			#action is a request from MCU aiming to get a result
			elif self.implements[action]['direction'] == 'result':
				message = params[required_params - 1]
				checksum = get_checksum(message)
				if not checksum in self.stash:
					result = { 
						"type": "result",
						"data": unserialize(message, False)
					}
					self.stash_put("out", checksum, result)
				elif self.has_result(checksum):
					out(1, checksum, self.get_result(checksum))
				else:
					out(0, "no_result")
			else:
				self.logger.warning("unknown behaviour action: %s" % action)
				out(0, "no_match")