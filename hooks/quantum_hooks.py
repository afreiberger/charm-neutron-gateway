#!/usr/bin/python

from base64 import b64decode

from charmhelpers.core.hookenv import (
    log, ERROR, WARNING,
    config,
    is_relation_made,
    relation_get,
    relation_set,
    relation_ids,
    unit_get,
    Hooks, UnregisteredHookError
)
from charmhelpers.fetch import (
    apt_update,
    apt_install,
    filter_installed_packages,
    apt_purge,
)
from charmhelpers.core.host import (
    restart_on_change,
    lsb_release,
)
from charmhelpers.contrib.hahelpers.cluster import(
    get_hacluster_config,
)
from charmhelpers.contrib.hahelpers.apache import(
    install_ca_cert
)
from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    openstack_upgrade_available,
)
from charmhelpers.payload.execd import execd_preinstall
from charmhelpers.core.sysctl import create as create_sysctl

from charmhelpers.contrib.charmsupport import nrpe

import sys
from quantum_utils import (
    register_configs,
    restart_map,
    services,
    do_openstack_upgrade,
    get_packages,
    get_early_packages,
    get_common_package,
    valid_plugin,
    configure_ovs,
    stop_services,
    cache_env_data,
    update_legacy_ha_files,
    remove_legacy_ha_files,
    add_hostname_to_hosts,
    install_legacy_ha_files,
    cleanup_ovs_netns,
    stop_neutron_ha_monitor_daemon
)

hooks = Hooks()
CONFIGS = register_configs()


@hooks.hook('install')
def install():
    execd_preinstall()
    src = config('openstack-origin')
    if (lsb_release()['DISTRIB_CODENAME'] == 'precise' and
            src == 'distro'):
        src = 'cloud:precise-folsom'
    configure_installation_source(src)
    apt_update(fatal=True)
    apt_install('python-six', fatal=True)  # Force upgrade
    if valid_plugin():
        apt_install(filter_installed_packages(get_early_packages()),
                    fatal=True)
        apt_install(filter_installed_packages(get_packages()),
                    fatal=True)
    else:
        log('Please provide a valid plugin config', level=ERROR)
        sys.exit(1)

    # Legacy HA for Icehouse
    update_legacy_ha_files()

    # Fix ovsdb-client monitor error
    add_hostname_to_hosts()


@hooks.hook('config-changed')
@restart_on_change(restart_map())
def config_changed():
    global CONFIGS
    if openstack_upgrade_available(get_common_package()):
        CONFIGS = do_openstack_upgrade()
    update_nrpe_config()

    sysctl_dict = config('sysctl')
    if sysctl_dict:
        create_sysctl(sysctl_dict, '/etc/sysctl.d/50-quantum-gateway.conf')

    # Re-run joined hooks as config might have changed
    for r_id in relation_ids('shared-db'):
        db_joined(relation_id=r_id)
    for r_id in relation_ids('pgsql-db'):
        pgsql_db_joined(relation_id=r_id)
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)
    for r_id in relation_ids('amqp-nova'):
        amqp_nova_joined(relation_id=r_id)
    if valid_plugin():
        CONFIGS.write_all()
        configure_ovs()
    else:
        log('Please provide a valid plugin config', level=ERROR)
        sys.exit(1)
    if config('plugin') == 'n1kv':
        if config('enable-l3-agent'):
            apt_install(filter_installed_packages('neutron-l3-agent'))
        else:
            apt_purge('neutron-l3-agent')

    # Setup legacy ha configurations
    update_legacy_ha_files()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    install()
    config_changed()
    update_legacy_ha_files(force=True)


@hooks.hook('shared-db-relation-joined')
def db_joined(relation_id=None):
    if is_relation_made('pgsql-db'):
        # raise error
        e = ('Attempting to associate a mysql database when there is already '
             'associated a postgresql one')
        log(e, level=ERROR)
        raise Exception(e)
    relation_set(username=config('database-user'),
                 database=config('database'),
                 hostname=unit_get('private-address'),
                 relation_id=relation_id)


@hooks.hook('pgsql-db-relation-joined')
def pgsql_db_joined(relation_id=None):
    if is_relation_made('shared-db'):
        # raise error
        e = ('Attempting to associate a postgresql database when there'
             ' is already associated a mysql one')
        log(e, level=ERROR)
        raise Exception(e)
    relation_set(database=config('database'),
                 relation_id=relation_id)


@hooks.hook('amqp-nova-relation-joined')
def amqp_nova_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('nova-rabbit-user'),
                 vhost=config('nova-rabbit-vhost'))


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'),
                 vhost=config('rabbit-vhost'))


@hooks.hook('amqp-nova-relation-departed')
@hooks.hook('amqp-nova-relation-changed')
@restart_on_change(restart_map())
def amqp_nova_changed():
    if 'amqp-nova' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write_all()


@hooks.hook('amqp-relation-departed')
@restart_on_change(restart_map())
def amqp_departed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write_all()


@hooks.hook('shared-db-relation-changed',
            'pgsql-db-relation-changed',
            'amqp-relation-changed',
            'cluster-relation-changed',
            'cluster-relation-joined',
            'neutron-plugin-api-relation-changed')
@restart_on_change(restart_map())
def db_amqp_changed():
    CONFIGS.write_all()


@hooks.hook('quantum-network-service-relation-changed')
@restart_on_change(restart_map())
def nm_changed():
    CONFIGS.write_all()
    if relation_get('ca_cert'):
        ca_crt = b64decode(relation_get('ca_cert'))
        install_ca_cert(ca_crt)

    if config('ha-legacy-mode'):
        cache_env_data()


@hooks.hook("cluster-relation-departed")
@restart_on_change(restart_map())
def cluster_departed():
    if config('plugin') in ['nvp', 'nsx']:
        log('Unable to re-assign agent resources for'
            ' failed nodes with nvp|nsx',
            level=WARNING)
        return
    if config('plugin') == 'n1kv':
        log('Unable to re-assign agent resources for failed nodes with n1kv',
            level=WARNING)
        return


@hooks.hook('cluster-relation-broken')
@hooks.hook('stop')
def stop():
    stop_services()
    if config('ha-legacy-mode'):
        # Cleanup ovs and netns for destroyed units.
        cleanup_ovs_netns()


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    apt_install('python-dbus')
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)
    nrpe.add_init_service_checks(nrpe_setup, services(), current_unit)

    cronpath = '/etc/cron.d/nagios-netns-check'
    cron_template = ('*/5 * * * * root '
                     '/usr/local/lib/nagios/plugins/check_netns.sh '
                     '> /var/lib/nagios/netns-check.txt\n'
                     )
    f = open(cronpath, 'w')
    f.write(cron_template)
    f.close()
    nrpe_setup.add_check(
        shortname="netns",
        description='Network Namespace check {%s}' % current_unit,
        check_cmd='check_status_file.py -f /var/lib/nagios/netns-check.txt'
        )
    nrpe_setup.write()


@hooks.hook('ha-relation-joined')
@hooks.hook('ha-relation-changed')
def ha_relation_joined():
    if config('ha-legacy-mode'):
        log('ha-relation-changed update_legacy_ha_files')
        install_legacy_ha_files()
        cache_env_data()
        cluster_config = get_hacluster_config(exclude_keys=['vip'])
        resources = {
            'res_monitor': 'ocf:canonical:NeutronAgentMon',
        }
        resource_params = {
            'res_monitor': 'op monitor interval="60s"',
        }
        clones = {
            'cl_monitor': 'res_monitor meta interleave="true"',
        }

        relation_set(corosync_bindiface=cluster_config['ha-bindiface'],
                     corosync_mcastport=cluster_config['ha-mcastport'],
                     resources=resources,
                     resource_params=resource_params,
                     clones=clones)


@hooks.hook('ha-relation-departed')
def ha_relation_destroyed():
    # If e.g. we want to upgrade to Juno and use native Neutron HA support then
    # we need to un-corosync-cluster to enable the transition.
    if config('ha-legacy-mode'):
        stop_neutron_ha_monitor_daemon()
        remove_legacy_ha_files()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
