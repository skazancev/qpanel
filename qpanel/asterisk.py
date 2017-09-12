# -*- coding: utf-8 -*-

#
# Class Qpanel for Asterisk
#
# Copyright (C) 2015-2017 Rodrigo Ramírez Norambuena <a@rodrigoramirez.com>
#

from __future__ import absolute_import, division

import calendar

from Asterisk.Manager import *

from qpanel.config import QPanelConfig
from qpanel.model import get_cdr, queuelog_count_answered, queuelog_event_by_range_and_types, QueueLog

from datetime import datetime, time


class ConnectionErrorAMI(Exception):
    '''
    This exception is raised when is not possible or is not connected to
    AMI for a requested action.
    '''
    _error = 'Not Connected'
    pass


config = QPanelConfig()

class AsteriskAMI:

    def __init__(self, host, port, user, password):
        '''
        Initialise a class for Asterisk
        '''
        self.host = host
        self.port = int(port)
        self.password = password
        self.user = user
        self.is_connected = False
        self.connection = self.connect_ami()
        self.core_channels = None
        self.config = config

    def connect_ami(self):
        try:
            manager = Manager((self.host, self.port), self.user, self.password)
            return manager
        except:
            return None

    def queueStatus(self):
        return self.getQueues()

    def getQueues(self):
        if self.connection is None:
            raise ConnectionErrorAMI(
                "Failed to connect to server at '{}:{}' for user {}\n"
                'Please check that Asterisk running and accepting AMI '
                'connections.'.format(self.host, self.port, self.user))

        cmd = self.connection.QueueStatus()
        return cmd

    def spy(self, channel, where_listen, option=None):
        '''Generate a Originate event by Manager to used Spy Application

        Parameters
        ----------
        channel: str
            channel to create Originate action tu use ChanSpy
        where_listen: str
            channel where listen the spy action.
        option: str
            other option to add for execute distinct options.
                whisper: w
                barge: B
            other string to add ChanSpy Command
            The option is concatenate to ',q'

        Returns
        -------
        originate result command : Dictionary
            if case the fail return return  {'Response': 'failed',
                                             'Message': str(msg)}
        '''

        options = ',q'
        if option:
            options = options + option
        try:
            # create a originate call for Spy a exten
            return self.connection.Originate(where_listen,
                                             application='ChanSpy',
                                             data=channel + options,
                                             async='yes')
        except Asterisk.Manager.ActionFailed as msg:
            return {'Response': 'failed', 'Message': str(msg)}
        except PermissionDenied as msg:
            return {'Response': 'failed', 'Message': 'Permission Denied'}

    def hangup(self, channel):
        """
        Hangup Channel

        Parameters
        ----------
        channel: str
            channel to hangup
        Returns
        -------
        hangup result action : Dictionary
            if case the fail return return  {'Response': 'failed',
                                             'Message': str(msg)}
        """
        try:
            # hangup channels
            return self.connection.Hangup(channel)
        except Asterisk.Manager.ActionFailed as msg:
            return {'Response': 'failed', 'Message': str(msg)}
        except PermissionDenied as msg:
            return {'Response': 'failed', 'Message': 'Permission Denied'}

    def reset_stats(self, queue):
        'Reset stats for <queue>.'
        id = self.connection._write_action('QueueReset', {'Queue': queue})
        return self.connection._translate_response(
            self.connection.read_response(id))

    def isConnected(self):
        if not self.connection:
            return False
        return True

    def remove_from_queue(self, agent, queue):
        '''Remove a <agent> from a <queue>

        Parameters
        ----------
        agent: str
            Agent or Inteface to remove
        queue: str
            name of queue from remove agent
        Returns
        -------
        originate result command : Dictionary
            if case the fail return return  {'Response': 'failed',
                                             'Message': str(msg)}
        '''
        try:
            return self.connection.QueueRemove(queue, agent)
        except Asterisk.Manager.ActionFailed as msg:
            return {'Response': 'failed', 'Message': str(msg)}
        except PermissionDenied as msg:
            return {'Response': 'failed', 'Message': 'Permission Denied'}

    def get_core_channels(self):
        if self.core_channels:
            return self.core_channels

        try:
            self.core_channels = self.connection.CoreShowChannels()
            return self.core_channels
        except AttributeError:
            return None

    def get_context_core_channels(self, context):
        core_channels = self.get_core_channels()
        if not core_channels:
            return

        channels = []
        for channel in core_channels:
            if channel.get('Context') == context:
                channels.append(channel)
        return channels

    def get_core_channels_count(self, context=None):
        if context:
            channel_list = self.get_context_core_channels(context)
        else:
            channel_list = self.get_core_channels()
        try:
            return len(channel_list) / 2
        except TypeError:
            return 0

    def get_calls_queue(self, queues):
        calls = self.get_context_core_channels(self.config.context_out)
        if not calls:
            return 0

        count = 0
        members = dict((key, value['members'].keys()) for key, value in queues.items())

        for call in calls:
            # TODO: Exten is agent name, name: LOCAL/79636815275@from-internal/nj
            if call.get('Exten') in members.get(call.get('Exten'), []):
                count += 1
        return count / 2

    def get_day_period(self):
        start = datetime.combine(datetime.now(), time.min)
        finish = datetime.combine(datetime.now(), time.max)
        return start, finish

    def get_month_period(self):
        date = datetime.now()
        start = datetime(date.year, date.month, 1)
        finish = datetime.combine(
            datetime(date.year, date.month, calendar.monthrange(date.year, date.month)[1]),
            time.max
        )
        return start, finish

    def get_period(self, period):
        try:
            return getattr(self, 'get_%s_period' % period)()
        except AttributeError:
            return None, None

    def parse_time(self, time):
        return datetime.strptime(time, '%Y-%m-%d %H:%M:%S.%f')

    def get_avg(self, event, period, **kwargs):
        try:
            obj_list = getattr(self, 'get_%s' % event)(**kwargs)
            if not obj_list:
                return 0

        except (AttributeError, TypeError):
            return 0

        start = self.parse_time(obj_list[0].time)
        finish = self.parse_time(obj_list[-1].time)
        days = (finish - start).days + 1
        size = 1

        if period == 'day':
            size = days
        elif period == 'month':
            size = days / 365 * 12

        return round(len(obj_list) / float(size))

    def parse_name(self, name):
        pattern = r'^[a-zA-Z]/([0-9]+)'
        names = re.findall(pattern, name)
        if names:
            return names[0]

        return name

    def get_outgoing(self, members, period=None):
        members = list(map(self.parse_name, members))
        data = {
            'members': members
        }

        if period:
            start, finish = self.get_period(period)
            data.update({
                'start': start,
                'finish': finish
            })

        return get_cdr(**data)

    def get_outgoing_avg(self, members, period):
        return self.get_avg('outgoing', period, members=members)

    def get_outgoing_count(self, members, period):
        return len(self.get_outgoing(members, period))

    def get_answered(self, queue=None, period=None, holdtime=config.holdtime):
        events = ['CONNECT']
        start, finish = self.get_period(period)
        query = queuelog_event_by_range_and_types(
            start, finish, events, queue=queue, order='queue_log.time ASC', query=False
        )

        if holdtime is None:
            return query.all()

        if holdtime > 0:
            return query.filter(QueueLog.data1 <= holdtime).all()
        else:
            return query.filter(QueueLog.data1 > holdtime).all()

    def get_answered_count(self, queue=None, period=None):
        return len(self.get_answered(queue, period))

    def get_answered_avg(self, queue=None, period=None):
        return self.get_avg('answered', period, queue=queue)

    def get_abandon(self, queue=None, period=None):
        start, finish = self.get_period(period)
        events = ['ABANDON']
        data = queuelog_event_by_range_and_types(
            start, finish, events, queue=queue, order='queue_log.time ASC'
        )
        data.extend(self.get_answered(period, -self.config.holdtime))
        return data

    def get_abandon_count(self, queue=None, period=None):
        return len(self.get_abandon(queue, period))

    def get_abandon_avg(self, queue=None, period=None):
        return self.get_avg('abandon', period, queue=queue)
