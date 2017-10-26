# -*- coding: utf-8 -*-

#
# Class Qpanel for Asterisk
#
# Copyright (C) 2015-2017 Rodrigo Ramírez Norambuena <a@rodrigoramirez.com>
#

from __future__ import absolute_import, division

import calendar

import math
from Asterisk.Manager import *

from qpanel.config import QPanelConfig
from qpanel.model import get_cdr, queuelog_event_by_range_and_types, QueueLog

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
        """
        Initialise a class for Asterisk
        """
        self.host = host
        self.port = int(port)
        self.password = password
        self.user = user
        self.is_connected = False
        self.connection = self.connect_ami()
        self.core_channels = None
        self.config = config
        self.answered = {}
        self.abandon = {}
        self.outgoing = {}

    def flush(self):
        self.answered, self.abandon, self.outgoing = {}, {}, {}

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
        """
        :return: Список каналов
        """
        # Возвращает self.core_channels если уже был вызван метод CoreShowChannels()
        if self.core_channels is None:
            return self.core_channels

        # Вызывает и записывает метод CoreShowChannels в self.core_channels
        try:
            self.core_channels = self.connection.CoreShowChannels()
            return self.core_channels
        except AttributeError:
            return None

    def get_context_core_channels(self, context):
        """
        :param context: from-internal, from-trunk
        :return: Список каналов с учетом context.
        """

        # Получаем список всех каналов
        core_channels = self.get_core_channels()
        if not core_channels:
            return

        channels = []

        # Если Context == context, то добавляет в список
        for channel in core_channels:
            if channel.get('Context') == context:
                channels.append(channel)
        return channels

    def get_core_channels_count(self, context=None):
        """
        :return: Количество каналов с учетом context
        """

        # Получаем список каналов с учетом context
        if context:
            channel_list = self.get_context_core_channels(context)
        else:
            channel_list = self.get_core_channels()

        # Длина списка полученных каналов делится на 2
        try:
            return len(channel_list) / 2
        except TypeError:
            return 0

    def get_calls_queue(self, queues=None, context=None, members=[]):
        """

        :param queues: очередь
        :param context: from-internal, from-trunk
        :param members: список агентов
        :return: Список звонков в очереди
        """

        # Получаем список каналов с учетом context
        calls = self.get_context_core_channels(context)

        if not calls:
            return []

        # Если есть очередь, то расширяем список агентов из очереди
        if queues:
            for key, value in queues.items():
                members.extend([v['Name'] for i, v in value['members'].items()])

        result = []

        # Если в списке агентов есть CallerIDNum канала, то добавляем в список результатов
        for call in calls:
            if self.get_channel_name(call.get('Channel')) in members:
                result.append(call)

        return result

    def get_channel_name(self, channel):
        try:
            return re.findall(r'^[^/]+/([^-]+)', channel.id)[0]
        except IndexError:
            return

    def get_calls_queue_count(self, queues, context=None):
        """

        :return: Количество звонков в очереди
        """
        return len(self.get_calls_queue(queues, context))

    def get_day_period(self):
        """

        :return: период дня от 00.00.00 до 23.59.59
        """
        start = datetime.combine(datetime.now(), time.min)
        finish = datetime.combine(datetime.now(), time.max)
        return start, finish

    def get_month_period(self):
        """

        :return: период всего месяца от 1 дня до 28/30/31
        """
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
        try:
            return datetime.strptime(time, '%Y-%m-%d %H:%M:%S')
        except TypeError:
            return time

    def get_avg(self, event, period, **kwargs):
        """
        Среднее арифметическое для списка звонков
        :param event: answered, outgoing, abandon
        :param period: day, month
        :return: среднее значение для event и period
        """

        # Получаем список объектов из методов
        # get_answered, get_abandon, get_outgoing
        try:
            obj_list = getattr(self, 'get_%s' % event)(**kwargs)
            if not obj_list:
                return 0

        except (AttributeError, TypeError) as e:
            return 0

        # obj_list отсортирован по времени
        # минимальная дата - первый объект
        # максимальная дата - последний объект
        start = self.parse_time(obj_list[0].as_dict()['time'])
        finish = self.parse_time(obj_list[-1].as_dict()['time'])
        days = (finish - start).days + 1
        size = 1
        # Получаем среднее арифметическое количество звонков для дня или месяца
        # День - длина obj_list / количество дней в периоде от минимальной даты до максимальной
        # Месяц - длина obj_list / количество дней в периоде от минимальной даты до максимальной / 365 * 12
        if period == 'day':
            size = days

        elif period == 'month':
            size = math.ceil(days / (365 / 12))

        try:
            return round(len(obj_list) / float(size))
        except ZeroDivisionError:
            return 0

    def parse_name(self, name):
        pattern = r'^[a-zA-Z]+/([0-9]+)'
        names = re.findall(pattern, name)
        if names:
            return names[0]

        return name

    def get_outgoing(self, members, period=None):
        """
        Исходящие звонки из таблицы CDR
        :param members: список агентов
        :param period: day, month
        :return: Список исходящих звонков для members и period
        """
        if period in self.outgoing:
            return self.outgoing[period]

        members = list(map(self.parse_name, members))
        data = {
            'members': members,
            'dcontext': 'from-internal'
        }

        if period:
            start, finish = self.get_period(period)
            data.update({
                'start': start,
                'finish': finish
            })
        self.outgoing[period] = get_cdr(**data)
        return self.outgoing[period]

    def get_outgoing_avg(self, members, period):
        return self.get_avg('outgoing', period, members=members)

    def get_outgoing_count(self, members, period):
        return len(self.get_outgoing(members, period))

    def get_answered(self, queue=None, period=None, holdtime=config.holdtime, query=True):
        """
        Список отвеченных звонков из таблицы QueueLog
        :param queue: Название очереди
        :param period: day, month
        :return: Список отвеченных звонков
        """
        if period and period in self.answered and query:
            return self.answered[period]

        events = ['CONNECT']

        # Получаем нужный нам период, начало и конец
        start, finish = self.get_period(period)

        # Формируем запрос в базу данных для таблицы QueueLog
        query = queuelog_event_by_range_and_types(
            start, finish, events, queue=queue, order=QueueLog.time.asc(), query=False
        )

        if holdtime is None:
            self.answered[period] = query.all()
            return self.answered[period]

        # Если время ожидания (holdtime) > 0, то фильтруем по полю data1 <= holdtime
        # Иначе, data1 > holdtime
        # Так, мы можем получить список отвеченных звонков либо до времени ожидания, либо после
        # После времени ожидания нужно для подсчета SLA и добавления количества звонков в Пропущенные
        if holdtime > 0:
            self.answered[period] = query.filter(QueueLog.data1 <= holdtime).all()
        else:
            self.answered[period] = query.filter(QueueLog.data1 > abs(holdtime)).all()

        return self.answered[period]

    def get_answered_count(self, queue=None, period=None, holdtime=config.holdtime):
        return len(self.get_answered(queue, period, holdtime))

    def get_answered_avg(self, queue=None, period=None, holdtime=None, query=True):
        return self.get_avg('answered', period, queue=queue, holdtime=holdtime, query=query)

    def get_abandon(self, queue=None, period=None, holdtime=True, query=True, write=True):
        """
        Список пропущенных звонков из таблицы QueueLog
        :param query: Делать ли повторный запрос
        :param holdtime: время ожидания
        :param queue: Название очереди
        :param period: day, month
        :return: Список пропущенных звонков
        """
        if period in self.abandon and query:
            return self.abandon[period]

        start, finish = self.get_period(period)
        events = ['ABANDON', 'EXITWITHTIMEOUT']
        # Формируем запрос в базу данных для таблицы QueueLog
        data = queuelog_event_by_range_and_types(
            start, finish, events, queue=queue, order=QueueLog.time.asc()
        )

        # Если есть время ожидания (holdtime), то прибавляем к списку пропущенных
        # звонков список отвеченных после времени ожидания
        if holdtime:
            data.extend(self.get_answered(period=period, holdtime=-self.config.holdtime, query=query))

        if write:
            self.abandon[period] = data

        return data

    def get_abandon_count(self, queue=None, period=None, holdtime=True, query=True, write=True):
        return len(self.get_abandon(queue, period, holdtime, query, write))

    def get_abandon_avg(self, queue=None, period=None):
        return self.get_avg('abandon', period, queue=queue, holdtime=False)

    def get_calls_count(self, queue=None, period=None):
        """
        :param queue: Название очереди
        :param period: day, month
        :return: Общее количество звонков за period
        """
        abandon = self.get_abandon_count(queue, period, write=False)
        answered = self.get_answered_count(queue, period)
        return abandon + answered

    def get_sla_abandon(self, queue=None, period=None, count=1):
        """
        Подсчет процента пропущенных звонков за period
        period = day
        count = 100
        количество пропущенных звонков за день - 2
        result 2 / 100 * 100 = 2%

        :param queue: Название очереди
        :param period: day, month
        :param count: количество пропущенных звонков
        :return: SLA для пропущенных звонков
        """
        try:
            result = self.get_abandon_count(queue, period, False, False) / count * 100
            return round(result)
        except ZeroDivisionError:
            return round(0)

    def get_sla_answered(self, queue=None, period=None, count=1):
        """
        Подсчет процента звонков, отвеченных после времени ожидания (holdtime) из config.ini за period
        period = day
        count = 100
        количество отвеченных звонков > holdtime за день - 2
        result 2 / 100 * 100 = 2%

        :param queue: Название очереди
        :param period: day, month
        :param count: количество отвеченных звонков
        :return: SLA для отвеченных звонков
        """
        try:
            result = self.get_abandon_count(queue, period, -self.config.holdtime, False) / count * 100
            return round(result)
        except ZeroDivisionError:
            return 0

    def get_members(self, members):
        """

        :return: Список занятых, свободных и недоступных линий
        """
        busy = []
        free = []
        unavailable = []
        # Если Status агента
        # == 1, то он свободен
        # == [0, 4, 5], то он недоступен
        # иначе он занят
        for name, member in members.items():
            status = int(member['Status'])
            if status == 1:
                free.append(member)
            elif status in [0, 4, 5]:
                unavailable.append(member)
            else:
                busy.append(member)
        return busy, free, unavailable

    def get_in_call(self, members):
        """

        :return: количество текущих звонков
        """
        # Если InCall агента == 1, то он находится в звонке
        return len([i for j, i in members.items() if i['InCall'] == '1'])
