# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# pylint: skip-file
import mock
import os
import requests
import tempfile
import unittest
import yaml

from msrestazure.azure_exceptions import CloudError
from azure.graphrbac.models import GraphErrorException
from azure.cli.command_modules.acs._params import (regions_in_preview,
                                                   regions_in_prod)
from azure.cli.command_modules.acs.custom import (merge_kubernetes_configurations, list_acs_locations,
                                                  _acs_browse_internal, _add_role_assignment, _get_default_dns_prefix,
                                                  create_application)
from azure.mgmt.containerservice.models import (ContainerServiceOrchestratorTypes,
                                                ContainerService,
                                                ContainerServiceOrchestratorProfile)
from azure.cli.core.util import CLIError


class AcsCustomCommandTest(unittest.TestCase):
    def test_list_acs_locations(self):
        client, cmd = mock.MagicMock(), mock.MagicMock()
        regions = list_acs_locations(client, cmd)
        prodregions = regions["productionRegions"]
        previewregions = regions["previewRegions"]
        self.assertListEqual(prodregions, regions_in_prod, "Production regions doesn't match")
        self.assertListEqual(previewregions, regions_in_preview, "Preview regions doesn't match")

    def test_get_default_dns_prefix(self):
        name = 'test5678910'
        resource_group_name = 'resource_group_with_underscore'
        sub_id = '123456789'

        dns_name_prefix = _get_default_dns_prefix(name, resource_group_name, sub_id)
        self.assertEqual(dns_name_prefix, "test567891-resourcegroupwit-123456")

        name = '1test5678910'
        dns_name_prefix = _get_default_dns_prefix(name, resource_group_name, sub_id)
        self.assertEqual(dns_name_prefix, "a1test5678-resourcegroupwit-123456")

    def test_add_role_assignment_basic(self):
        role = 'Owner'
        sp = '1234567'
        cli_ctx = mock.MagicMock()

        with mock.patch(
                'azure.cli.command_modules.acs.custom.create_role_assignment') as create_role_assignment:
            ok = _add_role_assignment(cli_ctx, role, sp, delay=0)
            create_role_assignment.assert_called_with(cli_ctx, role, sp)
            self.assertTrue(ok, 'Expected _add_role_assignment to succeed')

    def test_add_role_assignment_exists(self):
        role = 'Owner'
        sp = '1234567'
        cli_ctx = mock.MagicMock()

        with mock.patch(
                'azure.cli.command_modules.acs.custom.create_role_assignment') as create_role_assignment:
            resp = requests.Response()
            resp.status_code = 409
            resp._content = b'Conflict'
            err = CloudError(resp)
            err.message = 'The role assignment already exists.'
            create_role_assignment.side_effect = err
            ok = _add_role_assignment(cli_ctx, role, sp, delay=0)

            create_role_assignment.assert_called_with(cli_ctx, role, sp)
            self.assertTrue(ok, 'Expected _add_role_assignment to succeed')

    def test_add_role_assignment_fails(self):
        role = 'Owner'
        sp = '1234567'
        cli_ctx = mock.MagicMock()

        with mock.patch(
                'azure.cli.command_modules.acs.custom.create_role_assignment') as create_role_assignment:
            resp = requests.Response()
            resp.status_code = 500
            resp._content = b'Internal Error'
            err = CloudError(resp)
            err.message = 'Internal Error'
            create_role_assignment.side_effect = err
            ok = _add_role_assignment(cli_ctx, role, sp, delay=0)

            create_role_assignment.assert_called_with(cli_ctx, role, sp)
            self.assertFalse(ok, 'Expected _add_role_assignment to fail')

    @mock.patch('azure.cli.command_modules.acs.custom._get_subscription_id')
    def test_browse_k8s(self, get_subscription_id):
        acs_info = ContainerService("location", {}, {}, {})
        acs_info.orchestrator_profile = ContainerServiceOrchestratorProfile(
            ContainerServiceOrchestratorTypes.kubernetes)
        client, cmd = mock.MagicMock(), mock.MagicMock()

        with mock.patch('azure.cli.command_modules.acs.custom._get_acs_info',
                        return_value=acs_info) as get_acs_info:
            with mock.patch(
                    'azure.cli.command_modules.acs.custom._k8s_browse_internal') as k8s_browse:
                _acs_browse_internal(client, cmd, acs_info, 'resource-group', 'name', False, 'ssh/key/file')
                get_acs_info.assert_called_once()
                k8s_browse.assert_called_with('name', acs_info, False, 'ssh/key/file')

    @mock.patch('azure.cli.command_modules.acs.custom._get_subscription_id')
    def test_browse_dcos(self, get_subscription_id):
        acs_info = ContainerService("location", {}, {}, {})
        acs_info.orchestrator_profile = ContainerServiceOrchestratorProfile(
            ContainerServiceOrchestratorTypes.dcos)
        client, cmd = mock.MagicMock(), mock.MagicMock()

        with mock.patch(
                'azure.cli.command_modules.acs.custom._dcos_browse_internal') as dcos_browse:
            _acs_browse_internal(client, cmd, acs_info, 'resource-group', 'name', False, 'ssh/key/file')
            dcos_browse.assert_called_with(acs_info, False, 'ssh/key/file')

    def test_merge_credentials_non_existent(self):
        self.assertRaises(CLIError, merge_kubernetes_configurations, 'non', 'existent')

    def test_merge_credentials_broken_yaml(self):
        existing = tempfile.NamedTemporaryFile(delete=False)
        existing.close()
        addition = tempfile.NamedTemporaryFile(delete=False)
        addition.close()
        with open(existing.name, 'w+') as stream:
            stream.write('{ broken')
        self.addCleanup(os.remove, existing.name)

        obj2 = {
            'clusters': [
                'cluster2'
            ],
            'contexts': [
                'context2'
            ],
            'users': [
                'user2'
            ],
            'current-context': 'cluster2',
        }

        with open(addition.name, 'w+') as stream:
            yaml.dump(obj2, stream)
        self.addCleanup(os.remove, addition.name)

        self.assertRaises(CLIError, merge_kubernetes_configurations, existing.name, addition.name)

    def test_merge_credentials(self):
        existing = tempfile.NamedTemporaryFile(delete=False)
        existing.close()
        addition = tempfile.NamedTemporaryFile(delete=False)
        addition.close()
        obj1 = {
            'clusters': [
                'cluster1'
            ],
            'contexts': [
                'context1'
            ],
            'users': [
                'user1'
            ],
            'current-context': 'cluster1',
        }
        with open(existing.name, 'w+') as stream:
            yaml.dump(obj1, stream)
        self.addCleanup(os.remove, existing.name)

        obj2 = {
            'clusters': [
                'cluster2'
            ],
            'contexts': [
                'context2'
            ],
            'users': [
                'user2'
            ],
            'current-context': 'cluster2',
        }

        with open(addition.name, 'w+') as stream:
            yaml.dump(obj2, stream)
        self.addCleanup(os.remove, addition.name)

        merge_kubernetes_configurations(existing.name, addition.name)

        with open(existing.name, 'r') as stream:
            merged = yaml.load(stream)
        self.assertEqual(len(merged['clusters']), 2)
        self.assertEqual(merged['clusters'], ['cluster1', 'cluster2'])
        self.assertEqual(len(merged['contexts']), 2)
        self.assertEqual(merged['contexts'], ['context1', 'context2'])
        self.assertEqual(len(merged['users']), 2)
        self.assertEqual(merged['users'], ['user1', 'user2'])
        self.assertEqual(merged['current-context'], obj2['current-context'])

    def test_merge_credentials_missing(self):
        existing = tempfile.NamedTemporaryFile(delete=False)
        existing.close()
        addition = tempfile.NamedTemporaryFile(delete=False)
        addition.close()
        obj1 = {
            'clusters': None,
            'contexts': [
                'context1'
            ],
            'users': [
                'user1'
            ],
            'current-context': 'cluster1',
        }
        with open(existing.name, 'w+') as stream:
            yaml.dump(obj1, stream)
        self.addCleanup(os.remove, existing.name)

        obj2 = {
            'clusters': [
                'cluster2'
            ],
            'contexts': [
                'context2'
            ],
            'users': None,
            'current-context': 'cluster2',
        }

        with open(addition.name, 'w+') as stream:
            yaml.dump(obj2, stream)
        self.addCleanup(os.remove, addition.name)

        merge_kubernetes_configurations(existing.name, addition.name)

        with open(existing.name, 'r') as stream:
            merged = yaml.load(stream)
        self.assertEqual(len(merged['clusters']), 1)
        self.assertEqual(merged['clusters'], ['cluster2'])
        self.assertEqual(len(merged['contexts']), 2)
        self.assertEqual(merged['contexts'], ['context1', 'context2'])
        self.assertEqual(len(merged['users']), 1)
        self.assertEqual(merged['users'], ['user1'])
        self.assertEqual(merged['current-context'], obj2['current-context'])

    def test_merge_credentials_already_present(self):
        existing = tempfile.NamedTemporaryFile(delete=False)
        existing.close()
        addition = tempfile.NamedTemporaryFile(delete=False)
        addition.close()
        obj1 = {
            'clusters': [
                'cluster1',
                'cluster2'
            ],
            'contexts': [
                'context1',
                'context2'
            ],
            'users': [
                'user1',
                'user2'
            ],
            'current-context': 'cluster1',
        }
        with open(existing.name, 'w+') as stream:
            yaml.dump(obj1, stream)

        obj2 = {
            'clusters': [
                'cluster2'
            ],
            'contexts': [
                'context2'
            ],
            'users': [
                'user2'
            ],
            'current-context': 'cluster2',
        }

        with open(addition.name, 'w+') as stream:
            yaml.dump(obj2, stream)
        merge_kubernetes_configurations(existing.name, addition.name)
        self.addCleanup(os.remove, addition.name)

        with open(existing.name, 'r') as stream:
            merged = yaml.load(stream)
        self.addCleanup(os.remove, existing.name)

        self.assertEqual(len(merged['clusters']), 2)
        self.assertEqual(merged['clusters'], ['cluster1', 'cluster2'])
        self.assertEqual(len(merged['contexts']), 2)
        self.assertEqual(merged['contexts'], ['context1', 'context2'])
        self.assertEqual(len(merged['users']), 2)
        self.assertEqual(merged['users'], ['user1', 'user2'])
        self.assertEqual(merged['current-context'], obj2['current-context'])

    def test_acs_sp_create_failed_with_polished_error_if_due_to_permission(self):

        class FakedError(object):
            def __init__(self, message):
                self.message = message

        def _test_deserializer(resp_type, response):
            err = FakedError('Insufficient privileges to complete the operation')
            return err

        client = mock.MagicMock()
        client.create.side_effect = GraphErrorException(_test_deserializer, None)

        # action
        with self.assertRaises(CLIError) as context:
            create_application(client, 'acs_sp', 'http://acs_sp', ['http://acs_sp'])

        # assert we handled such error
        self.assertTrue('https://docs.microsoft.com/en-us/azure/azure-resource-manager/resource-group-create-service-principal-portal' in str(context.exception))
