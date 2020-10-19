#!/usr/bin/env python

import json, os, logging, requests
from datetime import datetime
from slackclient import SlackClient
from time import sleep
from syslog import LOG_DEBUG

__app_name__ = 'Slack-бот для резервирования тестовых серверов.'
__author__ = 'Jaishankar Padmanabhan'
__credits__ = ["Jaishankar Padmanabhan"]
__maintainer__ = 'Jaishankar Padmanabhan'
__email__ = 'jai.padmanabhan@gmail.com'

TIMEOUT = int(os.environ.get("TIMEOUT", "7200"))
TOKEN = os.environ.get("TOKEN", None)
DATA_FILE= os.environ.get("SERVERS_FILE", None)

#Debug logging
LOG_DEBUG=os.environ.get("LOG_DEBUG", "true")
if LOG_DEBUG == "false":
    logging.basicConfig(format='[%(filename)s:%(lineno)s] %(message)s', level=logging.INFO)
else:
    logging.basicConfig(format='[%(filename)s:%(lineno)s] %(message)s', level=logging.DEBUG)

log = logging.getLogger(__name__)
topics = {}

class QASlackBot:
  buildparams = {}
  client = None
  my_user_name = ''
  userdict = {}
  reservedict = {}
  channel = None
  message = None
  buildparamsList = []

  def userlist(self):
    api_call = self.client.api_call("users.list")
    if api_call.get('ok'):
      # retrieve all users
      users = api_call.get('members')
      for user in users:
         self.userdict[user['id']] = user['name']
    #log.debug(self.userdict)

  def connect(self, token):
    self.client = SlackClient(token)
    self.client.rtm_connect()
    self.my_user_name = self.client.server.username
    log.debug("Connected to Slack as "+ self.my_user_name)

  def listen(self):
    while True:
      try:
        input = self.client.rtm_read()
        if input:
          for action in input:
            log.debug(action)
            if 'type' in action and action['type'] == "message":
              self.process_message(action)
        else:
          sleep(1)

          # Check for time reserved and release when time is up
        for key in topics.keys():
            if key in self.reservedict:
                elapsed = datetime.now() - self.reservedict[key][1]
                if elapsed.total_seconds() > TIMEOUT:
                    msg = "@{0} уже 8 часов занимает сервер! Освобождаю `{1}`".format(self.reservedict[key][0], key)
                    log.debug( msg)
                    self.post(self.reservedict[key][2], msg)
                    del self.reservedict[key]

      except Exception as e:
        pass
        #log.error("Exception: ", e.message)

  def process_message(self, message):
    self.channel = message['channel']
    self.message = message['text']

    if self.message.lower().find(" help") == 12:
        self.help()
    elif self.message.lower().find(" status") == 12:
        self.status()

    for key in topics.keys():
      if self.message.lower().startswith("take " + key) or self.message.lower().startswith("t " + key) or self.message.lower().startswith(key + " take"):
        id = message['user']
        # Hold state of who is using the stack
        if  key not in self.reservedict :
            response = self.newreservation(key, id)
        else:
            response = self.existingReservation(key, id)
      elif key in self.reservedict and (self.message.lower().startswith("free " + key) or self.message.lower().startswith("f " + key) or self.message.lower().startswith(key + " free")):
          response = self.releaseStack(key)

  def post(self, channel, message):
    chan = self.client.server.channels.find(channel)
    if not chan:
      raise Exception("Channel %s not found." % channel)

    return chan.send_message(message)

  def help(self):
      self.post(self.channel, "```Добро пожаловать в систему резервации тестовых серверов! \n\n Список всех серверов:\n \
qa1\n qa2\n qa3\n qa4\n stage2\n sandbox1\n prod\n- Зарезервировать сервер: 't <server>' ИЛИ 'take <server>' ИЛИ '<server> take'\n- Освободить сервер: 'f <server>' ИЛИ 'free <server>' ИЛИ '<server> free'\n- Проверить статус свободных серверов: \
'@qabot status'\n\nЛимит использования - 8 часов. Если используете дольше, забейте снова.```")

  def status(self):
      if not self.reservedict.keys():
          self.post(self.channel, "Все свободно!")
      for key in self.reservedict.keys():
          response = topics[key].format(self.reservedict[key][0], key)
          self.post(self.channel, response)
          log.info(response)

  def newreservation(self, key, id):
      log.info("not there")
      self.reservedict[key] = [self.userdict[id], datetime.now(), self.channel]
      response = topics[key].format(self.userdict[id], key)
      log.info("Posting to {0}: {1}".format(self.channel, response))
      self.post(self.channel, response)

  def existingReservation(self, key, id):
      log.info("Stack already taken")
      response = "Сервер уже занят."
      log.info("Posting to {0}: {1}".format(self.channel, response))
      self.post(self.channel, response)

  def releaseStack(self, key):
      log.info("release by user")
      response = self.reservedict[key][0] + " занял сервер " + key
      self.post(self.reservedict[key][2], response)
      del self.reservedict[key]

# Main gateway
if __name__ == "__main__":

  if TOKEN is None:
        log.error("Slack Token is not set. Exiting.")
        exit()
  elif DATA_FILE is None:
        log.error("SERVERS_FILE is not set. Exiting.")
        exit()

  bot = QASlackBot()
  bot.connect(TOKEN)
  bot.userlist() # Build user id to name dictionary

  # Add our topics to the bot
  with open(DATA_FILE) as data_file:
    topics = json.load(data_file)

  # While loop to listen for messages on Slack
  bot.listen()
