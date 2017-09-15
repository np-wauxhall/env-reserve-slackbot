#!/usr/bin/env python

import argparse, ConfigParser, sys, json, os, logging, requests
from datetime import datetime
from slackclient import SlackClient
from time import sleep

__app_name__ = 'QA environment reservation Slack Bot'
__author__ = 'Jaishankar Padmanabhan'
__credits__ = ["Jaishankar Padmanabhan"]
__maintainer__ = 'Jaishankar Padmanabhan'
__email__ = 'jai.padmanabhan@gmail.com'

logging.basicConfig(format='[%(filename)s:%(lineno)s] %(message)s', level=logging.DEBUG)
log = logging.getLogger(__name__)

TIMEOUT=30
#Jenkins env variables
JENKINS=os.environ.get("JENKINS", "jenkins url")
JENKINS_URL= JENKINS+ "/buildByToken/buildWithParameters?job={0}&token={1}&Stack={2}"
JENKINS_TOKEN=os.environ.get("JENKINS_TOKEN", None)
JENKINS_RUBY_JOB=os.environ.get("JENKINS_RUBY_JOB", None)
JENKINS_JAVA_JOB=os.environ.get("JENKINS_JAVA_JOB", None)
JENKINS_FULL_JOB=os.environ.get("JENKINS_FULL_JOB", None)
JENKINS_RUBY_JOB_LINK=os.environ.get("JENKINS_RUBY_JOB_LINK", "jenkins url")
JENKINS_JAVA_JOB_LINK=os.environ.get("JENKINS_JAVA_JOB_LINK", "jenkins url")
JENKINS_FULL_JOB_LINK=os.environ.get("JENKINS_FULL_JOB_LINK", "jenkins url")

class QASlackBot:
  topics = {}
  buildparams = {}
  client = None
  my_user_name = ''
  userdict = {}
  reservedict = {}
  overridedict={}
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
         # pprint.pprint(self.userdict)


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
        for key in self.topics.keys():
            if key in self.reservedict:
                elapsed = datetime.now() - self.reservedict[key][1]
                if elapsed.total_seconds() > TIMEOUT:
                    msg = "@{0} 8 hrs up! Released stack `{1}`".format(self.reservedict[key][0], key)
                    log.debug( msg)
                    self.post(self.channel, msg)
                    del self.reservedict[key]

      except Exception as e:
        log.error("Exception: ", e.message)

  def process_message(self, message):
    self.channel = message['channel']
    self.message = message['text']

    if self.message.lower().find(" help") == 12:
        self.post(self.channel, "```Welcome to the QA environment reservation system! \nPlease type one of the following <stack> to reserve it.\n \
qa1\n qa2\n qa3\n qa4\n stage2\n sandbox1\nWhen you are done, type release <stack> OR <stack> release\nTo check current \
reservations, type @qabot status\nTo deploy to the reserved stack:\n<stack> deploy full OR\n<stack> deploy full | ApiVersion=SAV-3001-api,WebVersion=SAV-3000-web,\
RabbitConsumersVersion=master,AdminVersion=master,CsrVersion=master,Manifest=20170909\nDeploy Ruby only with <stack> deploy ruby \
OR <stack> deploy ruby | ApiVersion=master,WebVersion=SAV-3000-web\nDeploy Java only with <stack> deploy java OR <stack> deploy java | Manifest=20170909\n\
NOTE - There is a usage limit of 8 hours```")
    elif self.message.lower().find(" status") == 12:
        if not self.reservedict.keys():
          self.post(self.channel, "All stacks available!")
        for key in self.reservedict.keys():
            response = self.topics[key].format(self.reservedict[key][0], key)
            self.post(self.channel, response)
            log.info(response)

    for key in self.topics.keys():
      if self.message.lower().startswith(key) and self.message.lower().endswith(key) or self.message.lower().startswith("using " + key) or self.message.lower().startswith("on " + key):
        id = message['user']
        # Hold state of who is using the stack
        if  key not in self.reservedict :
            log.info( "not there")
            self.reservedict[key] = [self.userdict[id],  datetime.now()]
            response = self.topics[key].format(self.userdict[id], key)
            log.info("Posting to {0}: {1}".format(self.channel, response))
            self.post(self.channel, response)
        else:
            log.info("Stack already taken")
            self.overridedict[key] = self.userdict[id]
            response = self.topics[key].format(self.reservedict[key][0], key) + " . Are you sure you want to reserve it instead? Type `y` or `n`"
            log.info("Posting to {0}: {1}".format(self.channel, response))
            self.post(self.channel, response)
      elif key in self.reservedict and (self.message.lower().startswith("release " + key) or self.message.lower().startswith(key+" release")):
          log.info ("release by user")
          response = self.reservedict[key][0] + " has released stack " + key
          del self.reservedict[key]
          self.post(self.channel, response)

          # ************* Jenkins Deploy ******************
          # deploy full
      elif  self.message.lower().startswith(key) and " deploy" in self.message.lower() and self.message.lower().endswith(" full") :
          url = JENKINS_URL.format(JENKINS_FULL_JOB, JENKINS_TOKEN, key)
          if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
          else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")
          # deploy full | ApiVersion=master,WebVersion=SAV-3000
      elif self.message.lower().startswith(key) and (self.message.lower().find(" deploy") <  self.message.lower().find(" full")) and not self.message.lower().endswith("full") and "|" in self.message:
           log.info("Parsing build params")
           s = self.message.split("|")[1].strip()
           self.buildparams = dict(item.split("=") for item in s.split(","))
           log.info( self.buildparams)
           url = JENKINS_URL.format(JENKINS_FULL_JOB, JENKINS_TOKEN, key)
           if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
           else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")
           # deploy java
      elif self.message.lower().startswith(key) and " deploy" in self.message.lower() and self.message.lower().endswith(" java") :
          url = JENKINS_URL.format(JENKINS_JAVA_JOB, JENKINS_TOKEN, key)
          if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
          else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")
          # deploy java | Manifest=20170909
      elif self.message.lower().startswith(key) and (self.message.lower().find(" deploy") <  self.message.lower().find(" java")) and not self.message.lower().endswith("java") and "|" in self.message and "Manifest" in self.message:
           log.info("Parsing build params")
           s = self.message.split("|")[1].strip()
           self.buildparams = dict(item.split("=") for item in s.split(","))
           log.info( self.buildparams)
           url = JENKINS_URL.format(JENKINS_JAVA_JOB, JENKINS_TOKEN, key)
           if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
           else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")
           #deploy ruby
      elif self.message.lower().startswith(key) and " deploy" in self.message.lower() and self.message.lower().endswith(" ruby") :
          url = JENKINS_URL.format(JENKINS_RUBY_JOB, JENKINS_TOKEN, key)
          if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
          else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")
          # deploy ruby | ApiVersion=SAV-3000,WebVersion=master
      elif self.message.lower().startswith(key) and (self.message.lower().find(" deploy") <  self.message.lower().find(" ruby")) and not self.message.lower().endswith("java") and "|" in self.message and "Manifest" not in self.message:
           log.info("Parsing build params")
           s = self.message.split("|")[1].strip()
           self.buildparams = dict(item.split("=") for item in s.split(","))
           url = JENKINS_URL.format(JENKINS_RUBY_JOB, JENKINS_TOKEN, key)
           if self.reservedict and self.userdict[message['user']] in self.reservedict[key]:
            self.parseBuild(url, message)
           else:
              self.post(self.channel, "`Please reserve the stack before Jenkins deploy`")

          #respond to user's secondary msg
    if self.message.lower() == 'y' or self.message.lower() == 'yes':
        id = message['user']
        for key in self.overridedict.keys():
            if self.overridedict[key] == self.userdict[id]:
                log.info("take over")
                response = self.topics[key].format(self.overridedict[key], key)
                self.reservedict[key] = [self.overridedict[key],  datetime.now()]
                log.info("Posting to {0}: {1}".format(self.channel, response))
                self.post(self.channel, response)

        self.overridedict ={}


  def post(self, channel, message):
    chan = self.client.server.channels.find(channel)
    if not chan:
      raise Exception("Channel %s not found." % channel)

    return chan.send_message(message)

  def launchJenkins(self, url, message):
      log.debug(url)
      r = requests.get(url)
      if r.status_code != 201:
         self.post(self.channel, "`Could not launch Jenkins job !`s")
      else:
         log.info("Launched Jenkins job "+url)

  def parseBuild(self, url, message):
       flag=True
       for k in self.buildparams.keys():
               if k in self.buildparamsList:
                   url = url + "&" + k+ "=" +self.buildparams[k]
               else:
                   flag=False
                   self.post(self.channel, "`Check the parameters passed! Try @qabot help`")
       if flag:
          self.launchJenkins(url, message)
          link =""
          if "ruby" in url.lower():
              link = JENKINS_RUBY_JOB_LINK
          elif  "java" in url.lower():
              link = JENKINS_JAVA_JOB_LINK
          elif "full" in url.lower():
              link = JENKINS_FULL_JOB_LINK
          self.post(self.channel, "Jenkins job successfully launched at "+ link)

       self.buildparams = {}

# Main

if __name__ == "__main__":

  parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description='''
This script posts responses to trigger phrases.
Run with:
converse.py topics.json
''',
    epilog='''''')
  parser.add_argument('topics_file', type=str, nargs=1,
                   help='JSON of phrases/responses to read.')
  parser.add_argument('buildparams_file', type=str, nargs=1,
                   help='List of Jenkins parameters to read.')
  args = parser.parse_args()

  # Create a new Converser
  bot = QASlackBot()

  # Read our token and connect with it
  config = ConfigParser.RawConfigParser()
  config.read('creds.cfg')
  TOKEN = config.get("Slack", "token")
  JENKINS_TOKEN = config.get("Slack", "JENKINS_TOKEN")

  bot.connect(TOKEN)
  bot.userlist()

  # Add our topics to the bot
  with open(args.topics_file[0]) as data_file:
    bot.topics = json.load(data_file)

  with open(args.buildparams_file[0]) as data_file:
    bot.buildparamsList = data_file.read().splitlines()

  # Run our conversation loop.
  bot.listen()