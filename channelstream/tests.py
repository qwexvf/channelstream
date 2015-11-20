import pytest
from datetime import datetime, timedelta
from gevent.queue import Queue, Empty
from pyramid import testing
import channelstream
import channelstream.gc
from channelstream.channel import Channel
from channelstream.connection import Connection
from channelstream.user import User


class BaseInternalsTest(object):
    def setup_method(self, method):
        channelstream.CHANNELS = {}
        channelstream.CONNECTIONS = {}
        channelstream.USERS = {}


class TestChannel(BaseInternalsTest):
    def test_create_defaults(self):
        channel = Channel('test', long_name='long name')
        assert channel.name == 'test'
        assert channel.long_name == 'long name'
        assert channel.connections == {}
        assert channel.notify_presence is False
        assert channel.broadcast_presence_with_user_lists is False
        assert channel.salvageable is False
        assert channel.store_history is False
        assert channel.history_size == 10
        assert channel.history == []

    def test_repr(self):
        channel = Channel('test', long_name='long name')
        assert repr(channel) == '<Channel: test, connections:0>'

    @pytest.mark.parametrize('prop, value', [
        ('notify_presence', True),
        ('store_history', 6),
        ('history_size', 42),
        ('broadcast_presence_with_user_lists', True)
    ])
    def test_create_set_config(self, prop, value):
        channel_configs = {'test': {prop: value}}
        channel = Channel('test', channel_configs=channel_configs)

        assert getattr(channel, prop) == value

    def test_create_set_config_diff_name(self):
        channel_configs = {'test2': {'notify_presence': True}}
        channel = Channel('test', channel_configs=channel_configs)
        assert channel.notify_presence is False

    def test_add_connection(self):
        connection = Connection('test_user',
                                conn_id='A')
        channel = Channel('test')
        channel.add_connection(connection)
        assert len(channel.connections['test_user']) == 1
        assert 'test_user' in channel.connections
        assert connection in channel.connections['test_user']
        assert repr(channel) == '<Channel: test, connections:1>'

    def test_remove_connection(self):
        connection = Connection('test_user', conn_id='A')
        connection2 = Connection('test_user2', conn_id='B')
        connection3 = Connection('test_user', conn_id='C')
        channel = Channel('test')
        channel.add_connection(connection)
        channel.add_connection(connection2)
        channel.remove_connection(connection)
        assert 'test_user' not in channel.connections
        assert len(channel.connections['test_user2']) == 1
        channel.add_connection(connection)
        channel.add_connection(connection3)
        channel.remove_connection(connection)
        assert len(channel.connections['test_user']) == 1

    def test_remove_non_existant_connection(self):
        channel = Channel('test')
        connection = Connection('test_user', conn_id='A')
        channel.remove_connection(connection)
        assert 'test_user' not in channel.connections

    def test_remove_connection_w_presence(self):
        user = User('test_user')
        channelstream.USERS[user.username] = user
        connection = Connection('test_user', conn_id='A')
        user.add_connection(connection)
        config = {'test': {'notify_presence': True,
                           'broadcast_presence_with_user_lists': True}}
        channel = Channel('test', channel_configs=config)
        channel.add_connection(connection)
        channel.remove_connection(connection)

    def test_add_connection_w_presence(self):
        user = User('test_user')
        channelstream.USERS[user.username] = user
        connection = Connection('test_user', conn_id='A')
        user.add_connection(connection)
        config = {'test': {'notify_presence': True,
                           'broadcast_presence_with_user_lists': True}}
        channel = Channel('test', channel_configs=config)
        channel.add_connection(connection)
        assert len(channel.connections['test_user']) == 1
        assert 'test_user' in channel.connections
        assert connection in channel.connections['test_user']

    def test_presence_message(self):
        user = User('test_user')
        connection = Connection('test_user', conn_id='A')
        user.add_connection(connection)
        channel = Channel('test')
        channel.add_connection(connection)
        payload = channel.send_notify_presence_info('test_user', 'join')
        assert payload['user'] == 'test_user'
        assert payload['message']['action'] == 'join'
        assert payload['type'] == 'presence'
        assert payload['channel'] == 'test'
        assert len(payload['users']) == 0

    def test_presence_message_w_users(self):
        user = User('test_user')
        user.state_from_dict({'key': '1', 'key2': '2'})
        user.state_public_keys = ['key2']
        channelstream.USERS[user.username] = user
        connection = Connection('test_user', conn_id='A')
        user.add_connection(connection)
        user2 = User('test_user2')
        user2.state_from_dict({'key': '1', 'key2': '2'})
        channelstream.USERS[user2.username] = user2
        connection2 = Connection('test_user2', conn_id='A')
        user2.add_connection(connection2)
        config = {'test': {'notify_presence': True,
                           'broadcast_presence_with_user_lists': True}}
        channel = Channel('test', channel_configs=config)
        channel.add_connection(connection)
        channel.add_connection(connection2)
        payload = channel.send_notify_presence_info('test_user', 'join')
        assert len(payload['users']) == 2
        sorted_users = sorted(payload['users'], key=lambda x: x['user'])
        assert sorted_users == [
            {'state': {'key2': '2'}, 'user': 'test_user'},
            {'state': {}, 'user': 'test_user2'}
        ]

    def test_history(self):
        config = {'test': {'store_history': True,
                           'history_size': 3}}
        channel = Channel('test', long_name='long name', channel_configs=config)
        channel.add_message({'message': 'test1', 'type': 'message'})
        channel.add_message({'message': 'test2', 'type': 'message'})
        channel.add_message({'message': 'test3', 'type': 'message'})
        channel.add_message({'message': 'test4', 'type': 'message'})

        assert len(channel.history) == 3
        assert channel.history == [
            {'channel': 'test', 'message': 'test2', 'type': 'message'},
            {'channel': 'test', 'message': 'test3', 'type': 'message'},
            {'channel': 'test', 'message': 'test4', 'type': 'message'}
        ]


class TestConnection(BaseInternalsTest):
    def test_create_defaults(self):
        now = datetime.utcnow()
        connection = Connection('test', 'X')
        assert connection.username == 'test'
        assert now <= connection.last_active
        assert connection.socket is None
        assert connection.queue is None
        assert connection.id == 'X'

    def test_mark_for_gc(self):
        long_time_ago = datetime.utcnow() - timedelta(days=50)
        connection = Connection('test', 'X')
        connection.mark_for_gc()
        assert connection.last_active < long_time_ago

    def test_message(self):
        connection = Connection('test', 'X')
        connection.queue = Queue()
        connection.add_message({'message': 'test'})
        assert connection.queue.get() == [{'message': 'test'}]

    def test_heartbeat(self):
        connection = Connection('test', 'X')
        connection.queue = Queue()
        connection.heartbeat()
        assert connection.queue.get() == []


class TestUser(BaseInternalsTest):
    def test_create_defaults(self):
        user = User('test_user')
        user.state_from_dict({'key': '1', 'key2': '2'})
        user.state_public_keys = ['key2']
        assert repr(user) == '<User:test_user, connections:0>'
        assert sorted(user.state.items()) == sorted({'key': '1',
                                                     'key2': '2'}.items())
        assert user.public_state == {'key2': '2'}

    def test_messages(self):
        user = User('test_user')
        connection = Connection('test_user', conn_id='A')
        connection.queue = Queue()
        connection2 = Connection('test_user', conn_id='B')
        connection2.queue = Queue()
        user.add_connection(connection)
        user.add_connection(connection2)
        user.add_message({'type': 'message'})
        assert len(user.connections) == 2
        assert len(user.connections[0].queue.get()) == 1
        assert len(user.connections[1].queue.get()) == 1


class TestGC(BaseInternalsTest):
    def test_gc_connections_active(self):
        channel = Channel('test')
        channelstream.CHANNELS[channel.name] = channel
        channel2 = Channel('test2')
        channelstream.CHANNELS[channel2.name] = channel2
        user = User('test_user')
        channelstream.USERS[user.username] = user
        user2 = User('test_user2')
        channelstream.USERS[user2.username] = user2
        connection = Connection('test_user', '1')
        channelstream.CONNECTIONS[connection.id] = connection
        connection2 = Connection('test_user', '2')
        channelstream.CONNECTIONS[connection2.id] = connection2
        connection3 = Connection('test_user2', '3')
        channelstream.CONNECTIONS[connection3.id] = connection3
        connection4 = Connection('test_user2', '4')
        channelstream.CONNECTIONS[connection4.id] = connection4
        user.add_connection(connection)
        user.add_connection(connection2)
        channel.add_connection(connection)
        channel.add_connection(connection2)
        user2.add_connection(connection3)
        user2.add_connection(connection4)
        channel2.add_connection(connection3)
        channel2.add_connection(connection4)
        channelstream.gc.gc_conns()
        conns = channelstream.CHANNELS['test'].connections['test_user']
        assert len(conns) == 2
        assert len(channelstream.CONNECTIONS.items()) == 4
        conns = channelstream.CHANNELS['test2'].connections['test_user2']
        assert len(conns) == 2
        assert len(user.connections) == 2
        assert len(user2.connections) == 2
        assert sorted(channel.connections.keys()) == ['test_user']
        assert sorted(channel2.connections.keys()) == ['test_user2']

    def test_gc_connections_collecting(self):
        channel = Channel('test')
        channelstream.CHANNELS[channel.name] = channel
        channel2 = Channel('test2')
        channelstream.CHANNELS[channel2.name] = channel2
        user = User('test_user')
        channelstream.USERS[user.username] = user
        user2 = User('test_user2')
        channelstream.USERS[user2.username] = user2
        connection = Connection('test_user', '1')
        channelstream.CONNECTIONS[connection.id] = connection
        connection2 = Connection('test_user', '2')
        connection2.mark_for_gc()
        channelstream.CONNECTIONS[connection2.id] = connection2
        connection3 = Connection('test_user2', '3')
        connection3.mark_for_gc()
        channelstream.CONNECTIONS[connection3.id] = connection3
        connection4 = Connection('test_user2', '4')
        channelstream.CONNECTIONS[connection4.id] = connection4
        user.add_connection(connection)
        user.add_connection(connection2)
        channel.add_connection(connection)
        channel.add_connection(connection2)
        user2.add_connection(connection3)
        user2.add_connection(connection4)
        channel2.add_connection(connection3)
        channel2.add_connection(connection4)
        channelstream.gc.gc_conns()
        assert len(channelstream.CONNECTIONS.items()) == 2
        conns = channelstream.CHANNELS['test'].connections['test_user']
        assert len(conns) == 1
        assert conns == [connection]
        conns = channelstream.CHANNELS['test2'].connections['test_user2']
        assert len(conns) == 1
        assert conns == [connection4]
        assert len(user.connections) == 1
        assert len(user2.connections) == 1
        connection.mark_for_gc()
        connection4.mark_for_gc()
        channelstream.gc.gc_conns()
        assert 'test_user' not in channelstream.CHANNELS['test'].connections
        assert 'test_user2' not in channelstream.CHANNELS['test2'].connections
        assert len(channelstream.CHANNELS['test'].connections.items()) == 0
        assert len(channelstream.CHANNELS['test2'].connections.items()) == 0

    def test_users_active(self):
        user = User('test_user')
        channelstream.USERS[user.username] = user
        user2 = User('test_user2')
        channelstream.USERS[user2.username] = user2
        channelstream.gc.gc_users()
        assert len(channelstream.USERS.items()) == 2
        user.last_active -= timedelta(days=2)
        channelstream.gc.gc_users()
        assert len(channelstream.USERS.items()) == 1

def dummy_request():
    return testing.DummyRequest()


class BaseViewTest(BaseInternalsTest):
    def setup(self):
        self.config = testing.setUp(settings={})
        self.settings = self.config.get_settings()


class TestConnectViews(BaseViewTest):
    def setup(self):
        super(TestConnectViews, self).setup()
        from .wsgi_views.server import ServerViews
        self.view_cls = ServerViews(dummy_request())

        # def test_connect(self):
        #     result = self.view_cls.connect()
        #     print result
        #     assert 1 == 2


class TestStubState(BaseViewTest):
    def test_subscribe(self):
        pass

    def test_unsubscribe(self):
        pass

    def test__add_CORS(self):
        pass

    def test_handle_CORS(self):
        pass

    def test_message(self):
        pass

    def test_disconnect(self):
        pass

    def test_channel_config(self):
        pass

    def test_admin(self):
        pass

    def test_info(self):
        pass
