#
# Copyright (c) 2023-2024 Sandro Mani, Sourcepole AG
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

from qgis.core import *
from qgis.server import *
from qgis.PyQt.QtCore import QFile, QIODevice
from qgis.PyQt.QtXml import QDomDocument
import os

class PrintTemplatesFilter(QgsServerFilter):
    def __init__(self, serverIface):
        super(PrintTemplatesFilter, self).__init__(serverIface)
        self.__layouts = []
        self.__project = None
        
    def onRequestReady(self):
        
        #Only add print layouts for GetProjectSettings and for GetPrint
        request = self.serverInterface().requestHandler()
        requestParam = request.parameter('REQUEST').upper()
        if requestParam != 'GETPRINT': # and requestParam != 'GETPROJECTSETTINGS':
            return True
        
        template = request.parameter('TEMPLATE')
        parts = template.split("/")
        subdirpath = "/".join(parts[0:-1])
        templateName = parts[-1]
        request.setParameter('TEMPLATE', templateName)
        
        projectPath = self.serverInterface().configFilePath()
        self.__project = QgsConfigCache.instance().project( projectPath )

        if 'PRINT_LAYOUT_DIR' not in os.environ:
            QgsMessageLog.logMessage('PRINT_LAYOUT_DIR not set', 'plugin', Qgis.MessageLevel.Warning)
            return True

        QgsMessageLog.logMessage('Looking for templates in %s' % os.environ.get('PRINT_LAYOUT_DIR', ''), 'plugin', Qgis.MessageLevel.Info)
        
        layoutDir = os.path.join(os.environ['PRINT_LAYOUT_DIR'], subdirpath)
        for f in os.listdir(layoutDir):
            layoutFile = QFile(os.path.join(layoutDir,f))
            if not layoutFile.open( QIODevice.ReadOnly ):
                QgsMessageLog.logMessage('Opening file failed', 'plugin', Qgis.MessageLevel.Critical)
                continue
            domDoc = QDomDocument()
            if not domDoc.setContent(layoutFile):
                QgsMessageLog.logMessage('Reading xml document failed', 'plugin', Qgis.MessageLevel.Critical)
                continue

            #Check if template name maches template parameter in request
            if not domDoc.documentElement().attribute('name') == templateName:
                continue

            layout = QgsPrintLayout(self.__project)
            if not layout.readXml( domDoc.documentElement(), domDoc, QgsReadWriteContext() ):
                QgsMessageLog.logMessage('Reading layout failed', 'plugin', Qgis.MessageLevel.Critical)
            else:
                QgsMessageLog.logMessage('Reading of layout was successfull', 'plugin', Qgis.MessageLevel.Info)

            if not self.__project.layoutManager().addLayout(layout):
                QgsMessageLog.logMessage('Could not add layout to project', 'plugin', Qgis.MessageLevel.Critical)

            self.__layouts.append(layout)
            break
        
        return True
    
    def onResponseComplete(self):
        for layout in self.__layouts:
            self.__project.layoutManager().removeLayout(layout)
            
        self.__layouts.clear()
        self.__project = None
        
        return True

class PrintTemplates:
    def __init__(self, serverIface):
        self.iface = serverIface
        serverIface.registerFilter(PrintTemplatesFilter(serverIface))
