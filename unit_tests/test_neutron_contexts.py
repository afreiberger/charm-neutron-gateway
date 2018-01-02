from mock import (
    Mock,
    MagicMock,
    patch
)
import neutron_contexts
import sys
from contextlib import contextmanager

from test_utils import (
    CharmTestCase
)

TO_PATCH = [
    'apt_install',
    'config',
    'eligible_leader',
    'unit_get',
    'network_get_primary_address',
]


@contextmanager
def patch_open():
    '''Patch open() to allow mocking both open() itself and the file that is
    yielded.

    Yields the mock for "open" and "file", respectively.'''
    mock_open = MagicMock(spec=open)
    mock_file = MagicMock(spec=file)

    @contextmanager
    def stub_open(*args, **kwargs):
        mock_open(*args, **kwargs)
        yield mock_file

    with patch('__builtin__.open', stub_open):
        yield mock_open, mock_file


class DummyNeutronAPIContext():

    def __init__(self, return_value):
        self.return_value = return_value

    def __call__(self):
        return self.return_value


class TestL3AgentContext(CharmTestCase):

    def setUp(self):
        super(TestL3AgentContext, self).setUp(neutron_contexts,
                                              TO_PATCH)
        self.network_get_primary_address.side_effect = NotImplementedError
        self.config.side_effect = self.test_config.get

    @patch('neutron_contexts.NeutronAPIContext')
    def test_new_ext_network(self, _NeutronAPIContext):
        _NeutronAPIContext.return_value = \
            DummyNeutronAPIContext(return_value={'enable_dvr': False,
                                                 'report_interval': 30,
                                                 'rpc_response_timeout': 60,
                                                 })
        self.test_config.set('run-internal-router', 'none')
        self.test_config.set('external-network-id', '')
        self.eligible_leader.return_value = False
        self.assertEqual(neutron_contexts.L3AgentContext()(),
                         {'agent_mode': 'legacy',
                          'report_interval': 30,
                          'rpc_response_timeout': 60,
                          'external_configuration_new': True,
                          'handle_internal_only_router': False,
                          'plugin': 'ovs'})

    @patch('neutron_contexts.NeutronAPIContext')
    def test_old_ext_network(self, _NeutronAPIContext):
        _NeutronAPIContext.return_value = \
            DummyNeutronAPIContext(return_value={'enable_dvr': False,
                                                 'report_interval': 30,
                                                 'rpc_response_timeout': 60,
                                                 })
        self.test_config.set('run-internal-router', 'none')
        self.test_config.set('ext-port', 'eth1')
        self.eligible_leader.return_value = False
        self.assertEqual(neutron_contexts.L3AgentContext()(),
                         {'agent_mode': 'legacy',
                          'report_interval': 30,
                          'rpc_response_timeout': 60,
                          'handle_internal_only_router': False,
                          'plugin': 'ovs'})

    @patch('neutron_contexts.NeutronAPIContext')
    def test_hior_leader(self, _NeutronAPIContext):
        _NeutronAPIContext.return_value = \
            DummyNeutronAPIContext(return_value={'enable_dvr': False,
                                                 'report_interval': 30,
                                                 'rpc_response_timeout': 60,
                                                 })
        self.test_config.set('run-internal-router', 'leader')
        self.test_config.set('external-network-id', 'netid')
        self.eligible_leader.return_value = True
        self.assertEqual(neutron_contexts.L3AgentContext()(),
                         {'agent_mode': 'legacy',
                          'report_interval': 30,
                          'rpc_response_timeout': 60,
                          'handle_internal_only_router': True,
                          'ext_net_id': 'netid',
                          'plugin': 'ovs'})

    @patch('neutron_contexts.NeutronAPIContext')
    def test_hior_all(self, _NeutronAPIContext):
        _NeutronAPIContext.return_value = \
            DummyNeutronAPIContext(return_value={'enable_dvr': False,
                                                 'report_interval': 30,
                                                 'rpc_response_timeout': 60,
                                                 })
        self.test_config.set('run-internal-router', 'all')
        self.test_config.set('external-network-id', 'netid')
        self.eligible_leader.return_value = True
        self.assertEqual(neutron_contexts.L3AgentContext()(),
                         {'agent_mode': 'legacy',
                          'report_interval': 30,
                          'rpc_response_timeout': 60,
                          'handle_internal_only_router': True,
                          'ext_net_id': 'netid',
                          'plugin': 'ovs'})

    @patch('neutron_contexts.NeutronAPIContext')
    def test_dvr(self, _NeutronAPIContext):
        _NeutronAPIContext.return_value = \
            DummyNeutronAPIContext(return_value={'enable_dvr': True,
                                                 'report_interval': 30,
                                                 'rpc_response_timeout': 60,
                                                 })
        self.assertEqual(neutron_contexts.L3AgentContext()()['agent_mode'],
                         'dvr_snat')


class TestNeutronGatewayContext(CharmTestCase):

    def setUp(self):
        super(TestNeutronGatewayContext, self).setUp(neutron_contexts,
                                                     TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.maxDiff = None

    @patch('charmhelpers.contrib.openstack.context.relation_get')
    @patch('charmhelpers.contrib.openstack.context.related_units')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch.object(neutron_contexts, 'get_shared_secret')
    def test_all(self, _secret, _rids, _runits, _rget):
        rdata = {'l2-population': 'True',
                 'enable-dvr': 'True',
                 'overlay-network-type': 'gre',
                 'enable-l3ha': 'True',
                 'network-device-mtu': 9000,
                 'dns-domain': 'openstack.example.'}
        self.test_config.set('ovs-vsctl-timeout', 23)
        self.test_config.set('plugin', 'ovs')
        self.test_config.set('debug', False)
        self.test_config.set('verbose', True)
        self.test_config.set('instance-mtu', 1420)
        self.test_config.set('dnsmasq-flags', 'dhcp-userclass=set:ipxe,iPXE,'
                                              'dhcp-match=set:ipxe,175')
        self.test_config.set('dns-servers', '8.8.8.8,4.4.4.4')
        self.test_config.set('vlan-ranges',
                             'physnet1:1000:2000 physnet2:2001:3000')
        self.test_config.set('flat-network-providers', 'physnet3 physnet4')
        self.network_get_primary_address.side_effect = NotImplementedError
        self.unit_get.return_value = '10.5.0.1'
        # Provided by neutron-api relation
        _rids.return_value = ['neutron-plugin-api:0']
        _runits.return_value = ['neutron-api/0']
        _rget.side_effect = lambda *args, **kwargs: rdata
        _secret.return_value = 'testsecret'
        ctxt = neutron_contexts.NeutronGatewayContext()()
        self.assertEqual(ctxt, {
            'ovs_vsctl_timeout': 23,
            'shared_secret': 'testsecret',
            'enable_dvr': True,
            'enable_l3ha': True,
            'dns_servers': '8.8.8.8,4.4.4.4',
            'dns_domain': 'openstack.example.',
            'local_ip': '10.5.0.1',
            'instance_mtu': 1420,
            'core_plugin': "ml2",
            'plugin': 'ovs',
            'debug': False,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'gre',
            'report_interval': 30,
            'rpc_response_timeout': 60,
            'bridge_mappings': 'physnet1:br-data',
            'network_providers': 'physnet3,physnet4',
            'vlan_ranges': 'physnet1:1000:2000,physnet2:2001:3000',
            'network_device_mtu': 9000,
            'veth_mtu': 9000,
            'enable_isolated_metadata': False,
            'enable_metadata_network': False,
            'dnsmasq_flags': {
                'dhcp-userclass': 'set:ipxe,iPXE',
                'dhcp-match': 'set:ipxe,175'
            }
        })

    @patch('charmhelpers.contrib.openstack.context.relation_get')
    @patch('charmhelpers.contrib.openstack.context.related_units')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch.object(neutron_contexts, 'get_shared_secret')
    def test_all_network_spaces(self, _secret, _rids, _runits, _rget):
        rdata = {'l2-population': 'True',
                 'enable-dvr': 'True',
                 'overlay-network-type': 'gre',
                 'enable-l3ha': 'True',
                 'network-device-mtu': 9000,
                 'dns-domain': 'openstack.example.'}
        self.test_config.set('plugin', 'ovs')
        self.test_config.set('debug', False)
        self.test_config.set('verbose', True)
        self.test_config.set('instance-mtu', 1420)
        self.test_config.set('dnsmasq-flags', 'dhcp-userclass=set:ipxe,iPXE,'
                                              'dhcp-match=set:ipxe,175')
        self.test_config.set('vlan-ranges',
                             'physnet1:1000:2000 physnet2:2001:3000')
        self.test_config.set('flat-network-providers', 'physnet3 physnet4')
        self.network_get_primary_address.return_value = '192.168.20.2'
        self.unit_get.return_value = '10.5.0.1'
        # Provided by neutron-api relation
        _rids.return_value = ['neutron-plugin-api:0']
        _runits.return_value = ['neutron-api/0']
        _rget.side_effect = lambda *args, **kwargs: rdata
        _secret.return_value = 'testsecret'
        ctxt = neutron_contexts.NeutronGatewayContext()()
        self.assertEqual(ctxt, {
            'ovs_vsctl_timeout': 10,
            'shared_secret': 'testsecret',
            'enable_dvr': True,
            'enable_l3ha': True,
            'dns_servers': None,
            'dns_domain': 'openstack.example.',
            'local_ip': '192.168.20.2',
            'instance_mtu': 1420,
            'core_plugin': "ml2",
            'plugin': 'ovs',
            'debug': False,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'gre',
            'report_interval': 30,
            'rpc_response_timeout': 60,
            'bridge_mappings': 'physnet1:br-data',
            'network_providers': 'physnet3,physnet4',
            'vlan_ranges': 'physnet1:1000:2000,physnet2:2001:3000',
            'network_device_mtu': 9000,
            'veth_mtu': 9000,
            'enable_isolated_metadata': False,
            'enable_metadata_network': False,
            'dnsmasq_flags': {
                'dhcp-userclass': 'set:ipxe,iPXE',
                'dhcp-match': 'set:ipxe,175'
            }
        })

    @patch('charmhelpers.contrib.openstack.context.relation_get')
    @patch('charmhelpers.contrib.openstack.context.related_units')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch.object(neutron_contexts, 'get_shared_secret')
    def test_dhcp_settings(self, _secret, _rids, _runits, _rget):
        self.test_config.set('enable-isolated-metadata', True)
        self.test_config.set('enable-metadata-network', True)
        self.network_get_primary_address.return_value = '192.168.20.2'
        self.unit_get.return_value = '10.5.0.1'
        ctxt = neutron_contexts.NeutronGatewayContext()()
        self.assertTrue(ctxt['enable_isolated_metadata'])
        self.assertTrue(ctxt['enable_metadata_network'])

    @patch('charmhelpers.contrib.openstack.context.relation_get')
    @patch('charmhelpers.contrib.openstack.context.related_units')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    @patch.object(neutron_contexts, 'get_shared_secret')
    def test_dhcp_setting_plug_override(self, _secret, _rids, _runits, _rget):
        self.test_config.set('plugin', 'nsx')
        self.test_config.set('enable-isolated-metadata', False)
        self.test_config.set('enable-metadata-network', False)
        self.network_get_primary_address.return_value = '192.168.20.2'
        self.unit_get.return_value = '10.5.0.1'
        ctxt = neutron_contexts.NeutronGatewayContext()()
        self.assertTrue(ctxt['enable_isolated_metadata'])
        self.assertTrue(ctxt['enable_metadata_network'])


class TestSharedSecret(CharmTestCase):

    def setUp(self):
        super(TestSharedSecret, self).setUp(neutron_contexts,
                                            TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.network_get_primary_address.side_effect = NotImplementedError

    @patch('os.path')
    @patch('uuid.uuid4')
    def test_secret_created_stored(self, _uuid4, _path):
        _path.exists.return_value = False
        _uuid4.return_value = 'secret_thing'
        with patch_open() as (_open, _file):
            self.assertEqual(neutron_contexts.get_shared_secret(),
                             'secret_thing')
            _open.assert_called_with(
                neutron_contexts.SHARED_SECRET.format('neutron'), 'w')
            _file.write.assert_called_with('secret_thing')

    @patch('os.path')
    def test_secret_retrieved(self, _path):
        _path.exists.return_value = True
        with patch_open() as (_open, _file):
            _file.read.return_value = 'secret_thing\n'
            self.assertEqual(neutron_contexts.get_shared_secret(),
                             'secret_thing')
            _open.assert_called_with(
                neutron_contexts.SHARED_SECRET.format('neutron'), 'r')


class TestHostIP(CharmTestCase):

    def setUp(self):
        super(TestHostIP, self).setUp(neutron_contexts,
                                      TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.network_get_primary_address.side_effect = NotImplementedError
        # Save and inject
        self.mods = {'dns': None, 'dns.resolver': None}
        for mod in self.mods:
            if mod not in sys.modules:
                sys.modules[mod] = Mock()
            else:
                del self.mods[mod]

    def tearDown(self):
        super(TestHostIP, self).tearDown()
        # Cleanup
        for mod in self.mods.keys():
            del sys.modules[mod]

    def test_get_host_ip_already_ip(self):
        self.assertEqual(neutron_contexts.get_host_ip('10.5.0.1'),
                         '10.5.0.1')

    def test_get_host_ip_noarg(self):
        self.unit_get.return_value = "10.5.0.1"
        self.assertEqual(neutron_contexts.get_host_ip(),
                         '10.5.0.1')

    @patch('dns.resolver.query')
    def test_get_host_ip_hostname_unresolvable(self, _query):
        class NXDOMAIN(Exception):
            pass
        _query.side_effect = NXDOMAIN()
        self.assertRaises(NXDOMAIN, neutron_contexts.get_host_ip,
                          'missing.example.com')

    @patch('dns.resolver.query')
    def test_get_host_ip_hostname_resolvable(self, _query):
        data = MagicMock()
        data.address = '10.5.0.1'
        _query.return_value = [data]
        self.assertEqual(neutron_contexts.get_host_ip('myhost.example.com'),
                         '10.5.0.1')
        _query.assert_called_with('myhost.example.com', 'A')


class TestMisc(CharmTestCase):

    def setUp(self):
        super(TestMisc,
              self).setUp(neutron_contexts,
                          TO_PATCH)

    def test_core_plugin_ml2(self):
        self.config.return_value = 'ovs'
        self.assertEqual(neutron_contexts.core_plugin(),
                         neutron_contexts.NEUTRON_ML2_PLUGIN)
