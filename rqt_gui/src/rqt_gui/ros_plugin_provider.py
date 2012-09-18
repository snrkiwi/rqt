# Copyright (c) 2011, Dirk Thomas, Dorian Scholz, TU Darmstadt
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
#   * Neither the name of the TU Darmstadt nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import __builtin__
import os
import sys
import traceback

from xml.etree import ElementTree

from python_qt_binding.QtCore import qCritical

from qt_gui.plugin_descriptor import PluginDescriptor
from qt_gui.plugin_provider import PluginProvider

class RosPluginProvider(PluginProvider):

    """Base class for providing plugins based on the ROS package system."""

    _cached_plugins = {}

    def __init__(self, export_tag, base_class_type):
        super(RosPluginProvider, self).__init__()
        self.setObjectName('RosPluginProvider')

        self._export_tag = export_tag
        self._base_class_type = base_class_type
        self._plugin_descriptors = {}

    def discover(self):
        """
        Discover the plugins.
        The information of the `PluginDescriptor`s are extracted from the plugin manifests.
        """
        # search for plugins
        plugin_descriptors = []
        plugin_file_list = self._get_plugins(self._export_tag)
        for plugin_name, xml_file_name in plugin_file_list:
            plugin_descriptors += self._parse_plugin_xml(plugin_name, xml_file_name)
        # add list of discovered plugins to dictionary of known descriptors index by the plugin id
        for plugin_descriptor in plugin_descriptors:
            self._plugin_descriptors[plugin_descriptor.plugin_id()] = plugin_descriptor
        return plugin_descriptors

    def load(self, plugin_id, plugin_context):
        # get class reference from plugin descriptor
        attributes = self._plugin_descriptors[plugin_id].attributes()
        sys.path.append(attributes['module_base_path'])

        try:
            module = __builtin__.__import__(attributes['module_name'], fromlist=[attributes['class_from_class_type']], level=0)
        except NotImplementedError as e:
            qCritical('RosPluginProvider.load(%s): raised an exception:\n%s' % (plugin_id, e))
            return None
        except Exception as e:
            qCritical('RosPluginProvider.load(%s) exception raised in __builtin__.__import__(%s, [%s]):\n%s' % (plugin_id, attributes['module_name'], attributes['class_from_class_type'], traceback.format_exc()))
            raise e
        
        class_ref = getattr(module, attributes['class_from_class_type'], None)
        if class_ref is None:
            qCritical('RosPluginProvider.load(%s): could not find class "%s" in module "%s"' % (plugin_id, attributes['class_from_class_type']), module)
            return None

        # create plugin provider instance without context
        if class_ref.__init__.func_code.co_argcount == 1 and plugin_context is None:
            return class_ref()
        # create plugin instance
        return class_ref(plugin_context)

    def unload(self, plugin_instance):
        pass

    def _get_plugins(self, export_tag):
        # query available plugins only once
        if export_tag not in RosPluginProvider._cached_plugins.keys():
            RosPluginProvider._cached_plugins[export_tag] = self._find_plugins(export_tag)
        return RosPluginProvider._cached_plugins[export_tag]

    def _find_plugins(self, export_tag):
        raise NotImplementedError

    def _parse_plugin_xml(self, plugin_name, xml_file_name):
        plugin_descriptors = []
        plugin_path = os.path.dirname(os.path.abspath(xml_file_name))

        try:
            root = ElementTree.parse(xml_file_name)
        except Exception:
            qCritical('RosPluginProvider._parse_plugin_xml() could not parse "%s" of plugin "%s"' % (xml_file_name, plugin_name))
            return plugin_descriptors
        for library_el in root.getiterator('library'):
            library_path = library_el.attrib['path']

            for class_el in library_el.getiterator('class'):
                # collect common attributes
                attributes = {
                    'plugin_name': plugin_name,
                    'plugin_path': plugin_path,
                    'library_path': library_path,
                }

                # add class attributes
                for key, value in class_el.items():
                    attributes['class_' + key] = value

                # skip classes with non-matching _base_class_type
                class_base_class_type = attributes.get('class_base_class_type', None)
                if class_base_class_type != self._base_class_type:
                    continue

                # generate unique identifier
                plugin_id = plugin_name
                if 'class_name' in attributes:
                    plugin_id = plugin_id + '/' + attributes['class_name']
                attributes['plugin_id'] = plugin_id

                # base path to look for module
                module_base_path = plugin_path
                if library_path != '':
                    module_base_path = os.path.join(module_base_path, library_path)
                attributes['module_base_path'] = module_base_path

                # separate module name and class name
                module_name, class_from_class_type = os.path.split(attributes['class_type'].replace('.', os.sep))
                attributes['module_name'] = module_name.replace(os.sep, '.')
                attributes['class_from_class_type'] = class_from_class_type

                # check if plugin is available
                module_abs_path = os.path.join(module_base_path, module_name) + '.py'
                attributes['not_available'] = plugin_name if not os.path.exists(module_abs_path) else ''

                plugin_descriptor = PluginDescriptor(plugin_id, attributes)

                # set action attributes (plugin providers might have none)
                action_attributes, groups = self._parse_plugin(class_el)
                if len(action_attributes) > 0:
                    plugin_descriptor.set_action_attributes(
                        action_attributes['label'],
                        action_attributes.get('statustip', None),
                        action_attributes.get('icon', None),
                        action_attributes.get('icontype', None),
                    )
                # add group attributes
                for group in groups:
                    plugin_descriptor.add_group_attributes(
                        group['label'],
                        group.get('statustip', None),
                        group.get('icon', None),
                        group.get('icontype', None),
                    )

                # add plugin_descriptor to list 
                plugin_descriptors.append(plugin_descriptor)

        return plugin_descriptors

    def _parse_plugin(self, class_el):
        # create default plugin descriptor and group
        plugin_attributes = {}
        groups = []

        # update descriptor and group from qtgui tag
        guiplugin_el = class_el.find('qtgui')
        if guiplugin_el is not None:
            plugin_attributes.update(self._parse_action_group(guiplugin_el))
            for group_el in guiplugin_el.getiterator('group'):
                groups.append(self._parse_action_group(group_el))

        return plugin_attributes, groups

    def _parse_action_group(self, group_el):
        attributes = {}
        for tag in ['label', 'icon', 'statustip']:
            text = group_el.findtext(tag)
            if text:
                attributes[tag] = str(text)

        icon_el = group_el.find('icon')
        if icon_el is not None:
            icon_type_attrib = icon_el.get('type')
            if icon_type_attrib is not None:
                attributes['icontype'] = str(icon_type_attrib)

        return attributes
