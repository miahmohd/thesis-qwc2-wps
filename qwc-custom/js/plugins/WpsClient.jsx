/**
 * WPS Client Plugin for QWC2
 *
 * Allows users to browse, configure, and execute WPS 1.0.0 processes
 * served by a remote OGC WPS server (PyWPS).
 */

import React from 'react';
import { connect } from 'react-redux';

import axios from 'axios';
import { XMLParser } from 'fast-xml-parser';
import PropTypes from 'prop-types';

import { processFinished, processStarted } from 'qwc2/actions/processNotifications';
import SideBar from 'qwc2/components/SideBar';
import ComboBox from 'qwc2/components/widgets/ComboBox';
import NumberInput from 'qwc2/components/widgets/NumberInput';
import Spinner from 'qwc2/components/widgets/Spinner';

import './style/WpsClient.css';


const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 100;

class WpsClient extends React.Component {
    static propTypes = {
        /** URL of the WPS server */
        wpsUrl: PropTypes.string.isRequired,
        /** The side of the application on which to display the sidebar */
        side: PropTypes.string,
        processStarted: PropTypes.func,
        processFinished: PropTypes.func
    };
    static defaultProps = {
        side: 'right'
    };

    state = {
        // Process list
        processes: [],
        loadingProcesses: false,
        // Selected process
        selectedProcessId: '',
        processDescription: null,
        loadingDescription: false,
        // Form inputs
        formValues: {},
        validationErrors: {},
        // Execution
        executing: false,
        // Results
        results: null,
        error: null
    };

    pollTimer = null;
    pollCount = 0;

    componentWillUnmount() {
        this.stopPolling();
    }

    // =========================================================================
    // WPS GetCapabilities
    // =========================================================================

    fetchProcesses = () => {
        const { wpsUrl } = this.props;
        this.setState({ loadingProcesses: true, processes: [], error: null });

        const params = {
            service: 'WPS',
            request: 'GetCapabilities',
            version: '1.0.0'
        };

        axios.get(wpsUrl, { params })
            .then(response => {
                const parser = new XMLParser({
                    ignoreAttributes: false,
                    attributeNamePrefix: '@_',
                    removeNSPrefix: true
                });
                const result = parser.parse(response.data);
                const processes = this.extractProcesses(result);
                this.setState({ processes, loadingProcesses: false });
            })
            .catch(err => {
                this.setState({
                    loadingProcesses: false,
                    error: 'Failed to fetch processes: ' + (err.message || 'Unknown error')
                });
            });
    };

    extractProcesses = (parsed) => {
        try {
            const offerings = parsed.Capabilities?.ProcessOfferings?.Process;
            if (!offerings) return [];
            const list = Array.isArray(offerings) ? offerings : [offerings];
            return list.map(p => ({
                identifier: p.Identifier || '',
                title: p.Title || p.Identifier || '',
                abstract: p.Abstract || ''
            }));
        } catch {
            return [];
        }
    };

    // =========================================================================
    // WPS DescribeProcess
    // =========================================================================

    fetchProcessDescription = (identifier) => {
        const { wpsUrl } = this.props;
        this.setState({ loadingDescription: true, processDescription: null, formValues: {}, validationErrors: {}, results: null, error: null });

        const params = {
            service: 'WPS',
            request: 'DescribeProcess',
            version: '1.0.0',
            identifier: identifier
        };

        axios.get(wpsUrl, { params })
            .then(response => {
                const parser = new XMLParser({
                    ignoreAttributes: false,
                    attributeNamePrefix: '@_',
                    removeNSPrefix: true
                });
                const result = parser.parse(response.data);
                const description = this.extractDescription(result);
                // Initialize form with default values
                const formValues = {};
                if (description && description.inputs) {
                    description.inputs.forEach(input => {
                        formValues[input.identifier] = input.defaultValue || '';
                    });
                }
                this.setState({ processDescription: description, loadingDescription: false, formValues });
            })
            .catch(err => {
                this.setState({
                    loadingDescription: false,
                    error: 'Failed to describe process: ' + (err.message || 'Unknown error')
                });
            });
    };

    extractDescription = (parsed) => {
        try {
            const descriptions = parsed.ProcessDescriptions?.ProcessDescription;
            const desc = Array.isArray(descriptions) ? descriptions[0] : descriptions;
            if (!desc) return null;

            const storeSupported = desc['@_storeSupported'] === 'true';
            const statusSupported = desc['@_statusSupported'] === 'true';

            // Extract inputs
            const dataInputs = desc.DataInputs?.Input;
            const inputList = dataInputs ? (Array.isArray(dataInputs) ? dataInputs : [dataInputs]) : [];

            const inputs = inputList.map(input => {
                const literalData = input.LiteralData;
                const minOccurs = parseInt(input['@_minOccurs'] || '1', 10);
                const identifier = input.Identifier || '';
                const title = input.Title || identifier;
                const abstract = input.Abstract || '';

                let dataType = 'string';
                let allowedValues = null;
                let defaultValue = '';

                if (literalData) {
                    dataType = this.parseLiteralDataType(literalData.DataType);
                    defaultValue = literalData.DefaultValue || '';

                    const av = literalData.AllowedValues;
                    if (av) {
                        const values = av.Value;
                        if (values) {
                            allowedValues = Array.isArray(values) ? values : [values];
                        }
                    }
                    // Check for AnyValue (no restrictions)
                    // If AllowedValues is not defined but AnyValue is, leave allowedValues null
                }

                return {
                    identifier,
                    title,
                    abstract,
                    dataType,
                    minOccurs,
                    allowedValues,
                    defaultValue: defaultValue.toString()
                };
            });

            // Extract outputs
            const processOutputs = desc.ProcessOutputs?.Output;
            const outputList = processOutputs ? (Array.isArray(processOutputs) ? processOutputs : [processOutputs]) : [];

            const outputs = outputList.map(output => ({
                identifier: output.Identifier || '',
                title: output.Title || output.Identifier || '',
                abstract: output.Abstract || ''
            }));

            return {
                identifier: desc.Identifier || '',
                title: desc.Title || '',
                abstract: desc.Abstract || '',
                storeSupported,
                statusSupported,
                inputs,
                outputs
            };
        } catch {
            return null;
        }
    };

    parseLiteralDataType = (dataType) => {
        if (!dataType) return 'string';
        const typeStr = (typeof dataType === 'string' ? dataType : dataType['#text'] || '').toLowerCase();
        if (typeStr.includes('integer') || typeStr.includes('int')) return 'integer';
        if (typeStr.includes('float') || typeStr.includes('double') || typeStr.includes('decimal')) return 'float';
        if (typeStr.includes('boolean') || typeStr.includes('bool')) return 'boolean';
        return 'string';
    };

    // =========================================================================
    // Form handling
    // =========================================================================

    handleInputChange = (identifier, value) => {
        this.setState(prevState => ({
            formValues: { ...prevState.formValues, [identifier]: value },
            validationErrors: { ...prevState.validationErrors, [identifier]: null }
        }));
    };

    validateForm = () => {
        const { processDescription, formValues } = this.state;
        if (!processDescription) return false;

        const errors = {};
        let valid = true;

        processDescription.inputs.forEach(input => {
            const value = formValues[input.identifier];
            // Required check
            if (input.minOccurs > 0 && (!value && value !== 0)) {
                errors[input.identifier] = 'This field is required';
                valid = false;
            }
            // Type check
            if (value && input.dataType === 'integer') {
                if (!/^-?\d+$/.test(value.toString())) {
                    errors[input.identifier] = 'Must be an integer';
                    valid = false;
                }
            }
            if (value && input.dataType === 'float') {
                if (isNaN(parseFloat(value))) {
                    errors[input.identifier] = 'Must be a number';
                    valid = false;
                }
            }
        });

        this.setState({ validationErrors: errors });
        return valid;
    };

    // =========================================================================
    // WPS Execute
    // =========================================================================

    executeProcess = () => {
        if (!this.validateForm()) return;

        const { processDescription, formValues } = this.state;
        if (!processDescription) return;

        const useAsync = processDescription.storeSupported && processDescription.statusSupported;
        const requestXml = this.buildExecuteRequest(processDescription, formValues, useAsync);

        this.setState({ executing: true, results: null, error: null });

        const processId = processDescription.identifier + '_' + Date.now();
        if (useAsync) {
            this.props.processStarted(processId, processDescription.title);
        }

        axios.post(this.props.wpsUrl, requestXml, {
            headers: { 'Content-Type': 'application/xml' }
        })
            .then(response => {
                const parser = new XMLParser({
                    ignoreAttributes: false,
                    attributeNamePrefix: '@_',
                    removeNSPrefix: true
                });
                const result = parser.parse(response.data);

                // Check for exception
                const exception = this.extractException(result);
                if (exception) {
                    this.setState({ executing: false, error: exception });
                    if (useAsync) {
                        this.props.processFinished(processId, false, exception);
                    }
                    return;
                }

                if (useAsync) {
                    // Check status
                    const status = this.extractStatus(result);
                    if (status === 'ProcessAccepted' || status === 'ProcessStarted') {
                        const statusLocation = this.extractStatusLocation(result);
                        if (statusLocation) {
                            this.startPolling(statusLocation, processId);
                        } else {
                            this.setState({ executing: false, error: 'No status location returned' });
                            this.props.processFinished(processId, false, 'No status location');
                        }
                    } else if (status === 'ProcessSucceeded') {
                        const outputs = this.extractOutputs(result);
                        this.setState({ executing: false, results: outputs });
                        this.props.processFinished(processId, true, 'Process completed');
                    } else if (status === 'ProcessFailed') {
                        const failMsg = this.extractFailureMessage(result) || 'Process failed';
                        this.setState({ executing: false, error: failMsg });
                        this.props.processFinished(processId, false, failMsg);
                    }
                } else {
                    // Synchronous - extract results directly
                    const outputs = this.extractOutputs(result);
                    if (outputs) {
                        this.setState({ executing: false, results: outputs });
                    } else {
                        this.setState({ executing: false, error: 'No outputs returned' });
                    }
                }
            })
            .catch(err => {
                const errMsg = 'Execution failed: ' + (err.message || 'Unknown error');
                this.setState({ executing: false, error: errMsg });
                if (useAsync) {
                    this.props.processFinished(processId, false, errMsg);
                }
            });
    };

    buildExecuteRequest = (description, values, useAsync) => {
        const inputs = description.inputs
            .filter(input => values[input.identifier] !== '' && values[input.identifier] !== undefined)
            .map(input => {
                return `    <wps:Input>
      <ows:Identifier>${input.identifier}</ows:Identifier>
      <wps:Data>
        <wps:LiteralData>${this.escapeXml(values[input.identifier].toString())}</wps:LiteralData>
      </wps:Data>
    </wps:Input>`;
            }).join('\n');

        const responseForm = description.outputs.map(output => {
            return `      <wps:Output>
        <ows:Identifier>${output.identifier}</ows:Identifier>
      </wps:Output>`;
        }).join('\n');

        const storeAttr = useAsync ? ' storeExecuteResponse="true" status="true"' : '';

        return `<?xml version="1.0" encoding="UTF-8"?>
<wps:Execute version="1.0.0" service="WPS"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns="http://www.opengis.net/wps/1.0.0"
 xmlns:wfs="http://www.opengis.net/wfs"
 xmlns:wps="http://www.opengis.net/wps/1.0.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"
 xmlns:gml="http://www.opengis.net/gml"
 xmlns:ogc="http://www.opengis.net/ogc"
 xmlns:wcs="http://www.opengis.net/wcs/1.1.1"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xsi:schemaLocation="http://www.opengis.net/wps/1.0.0 http://schemas.opengis.net/wps/1.0.0/wpsAll.xsd">
  <ows:Identifier>${description.identifier}</ows:Identifier>
  <wps:DataInputs>
${inputs}
  </wps:DataInputs>
  <wps:ResponseForm>
    <wps:ResponseDocument${storeAttr}>
${responseForm}
    </wps:ResponseDocument>
  </wps:ResponseForm>
</wps:Execute>`;
    };

    escapeXml = (str) => {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&apos;');
    };

    // =========================================================================
    // Async polling
    // =========================================================================

    startPolling = (statusLocation, processId) => {
        this.pollCount = 0;
        this.pollProcessId = processId;
        this.pollStatusLocation = statusLocation;
        this.pollTimer = setInterval(() => this.pollStatus(), POLL_INTERVAL_MS);
    };

    stopPolling = () => {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    };

    pollStatus = () => {
        this.pollCount++;
        if (this.pollCount > MAX_POLL_ATTEMPTS) {
            this.stopPolling();
            const errMsg = 'Process timed out after ' + (MAX_POLL_ATTEMPTS * POLL_INTERVAL_MS / 1000) + ' seconds';
            this.setState({ executing: false, error: errMsg });
            this.props.processFinished(this.pollProcessId, false, errMsg);
            return;
        }

        axios.get(this.pollStatusLocation)
            .then(response => {
                const parser = new XMLParser({
                    ignoreAttributes: false,
                    attributeNamePrefix: '@_',
                    removeNSPrefix: true
                });
                const result = parser.parse(response.data);

                const exception = this.extractException(result);
                if (exception) {
                    this.stopPolling();
                    this.setState({ executing: false, error: exception });
                    this.props.processFinished(this.pollProcessId, false, exception);
                    return;
                }

                const status = this.extractStatus(result);
                if (status === 'ProcessSucceeded') {
                    this.stopPolling();
                    const outputs = this.extractOutputs(result);
                    this.setState({ executing: false, results: outputs });
                    this.props.processFinished(this.pollProcessId, true, 'Process completed');
                } else if (status === 'ProcessFailed') {
                    this.stopPolling();
                    const failMsg = this.extractFailureMessage(result) || 'Process failed';
                    this.setState({ executing: false, error: failMsg });
                    this.props.processFinished(this.pollProcessId, false, failMsg);
                }
                // ProcessAccepted / ProcessStarted => keep polling
            })
            .catch(err => {
                this.stopPolling();
                const errMsg = 'Polling failed: ' + (err.message || 'Unknown error');
                this.setState({ executing: false, error: errMsg });
                this.props.processFinished(this.pollProcessId, false, errMsg);
            });
    };

    // =========================================================================
    // Response parsing helpers
    // =========================================================================

    extractException = (parsed) => {
        const report = parsed.ExceptionReport || parsed.Exception;
        if (report) {
            const ex = report.Exception || report;
            const exArr = Array.isArray(ex) ? ex : [ex];
            return exArr.map(e => e.ExceptionText || e['@_exceptionCode'] || 'Unknown error').join('; ');
        }
        return null;
    };

    extractStatus = (parsed) => {
        const response = parsed.ExecuteResponse;
        if (!response) return null;
        const status = response.Status;
        if (!status) return null;
        if (status.ProcessAccepted !== undefined) return 'ProcessAccepted';
        if (status.ProcessStarted !== undefined) return 'ProcessStarted';
        if (status.ProcessSucceeded !== undefined) return 'ProcessSucceeded';
        if (status.ProcessFailed !== undefined) return 'ProcessFailed';
        return null;
    };

    extractStatusLocation = (parsed) => {
        const response = parsed.ExecuteResponse;
        return response ? response['@_statusLocation'] : null;
    };

    extractFailureMessage = (parsed) => {
        const response = parsed.ExecuteResponse;
        if (!response || !response.Status || !response.Status.ProcessFailed) return null;
        const exReport = response.Status.ProcessFailed.ExceptionReport;
        if (exReport) {
            const ex = exReport.Exception;
            if (ex) {
                const exArr = Array.isArray(ex) ? ex : [ex];
                return exArr.map(e => e.ExceptionText || '').join('; ');
            }
        }
        return null;
    };

    extractOutputs = (parsed) => {
        const response = parsed.ExecuteResponse;
        if (!response || !response.ProcessOutputs) return null;
        const outputDefs = response.ProcessOutputs.Output;
        if (!outputDefs) return null;
        const outputs = Array.isArray(outputDefs) ? outputDefs : [outputDefs];

        return outputs.map(output => {
            const identifier = output.Identifier || '';
            const title = output.Title || identifier;
            let value = '';
            if (output.Data) {
                if (output.Data.LiteralData !== undefined) {
                    console.log("output.Data", output.Data)
                    value = output.Data.LiteralData["#text"] || JSON.stringify(output.Data.LiteralData);
                }
            }
            return { identifier, title, value };
        });
    };

    // =========================================================================
    // Event handlers
    // =========================================================================

    onProcessSelected = (identifier) => {
        this.setState({ selectedProcessId: identifier, results: null, error: null });
        if (identifier) {
            this.fetchProcessDescription(identifier);
        } else {
            this.setState({ processDescription: null, formValues: {}, validationErrors: {} });
        }
    };

    onShow = () => {
        this.fetchProcesses();
    };

    onHide = () => {
        this.stopPolling();
        this.setState({
            processes: [],
            selectedProcessId: '',
            processDescription: null,
            formValues: {},
            validationErrors: {},
            executing: false,
            results: null,
            error: null
        });
    };

    // =========================================================================
    // Render
    // =========================================================================

    render() {
        return (
            <SideBar
                icon="gears"
                id="WpsClient"
                onHide={this.onHide}
                onShow={this.onShow}
                side={this.props.side}
                title="WPS Client"
                width="20em"
            >
                {() => ({
                    body: this.renderBody()
                })}
            </SideBar>
        );
    }

    renderBody = () => {
        const { loadingProcesses, error } = this.state;

        return (
            <div className="wps-client-body">
                {this.renderProcessSelector()}
                {loadingProcesses && <div className="wps-client-loading"><Spinner /> Loading processes...</div>}
                {this.renderForm()}
                {this.renderResults()}
                {error && <div className="wps-client-error">{error}</div>}
            </div>
        );
    };

    renderProcessSelector = () => {
        const { processes, selectedProcessId, loadingProcesses } = this.state;

        if (loadingProcesses) return null;

        return (
            <div className="wps-client-section">
                <label className="wps-client-label">Process:</label>
                <ComboBox
                    filterable
                    onChange={this.onProcessSelected}
                    placeholder="Select a process..."
                    value={selectedProcessId}
                >
                    {processes.map(p => (
                        <span key={p.identifier} title={p.title} value={p.identifier}>
                            {p.title}
                        </span>
                    ))}
                </ComboBox>
                {selectedProcessId && this.state.processDescription && (
                    <div className="wps-client-abstract">
                        {this.state.processDescription.abstract}
                    </div>
                )}
            </div>
        );
    };

    renderForm = () => {
        const { processDescription, loadingDescription, formValues, validationErrors, executing } = this.state;

        if (loadingDescription) {
            return <div className="wps-client-loading"><Spinner /> Loading process details...</div>;
        }

        if (!processDescription) return null;

        return (
            <div className="wps-client-section wps-client-form">
                <label className="wps-client-label">Inputs:</label>
                {processDescription.inputs.length === 0 && (
                    <div className="wps-client-no-inputs">This process has no inputs.</div>
                )}
                {processDescription.inputs.map(input => this.renderInputField(input, formValues, validationErrors))}
                <div className="wps-client-execute">
                    {executing ? (
                        <div className="wps-client-loading"><Spinner /> Executing...</div>
                    ) : (
                        <button className="button" onClick={this.executeProcess}>
                            Run
                        </button>
                    )}
                </div>
            </div>
        );
    };

    renderInputField = (input, formValues, validationErrors) => {
        const value = formValues[input.identifier] || '';
        const error = validationErrors[input.identifier];
        const required = input.minOccurs > 0;

        return (
            <div className="wps-client-input-group" key={input.identifier}>
                <label className="wps-client-input-label">
                    {input.title}
                    {required && <span className="wps-client-required">*</span>}
                </label>
                {input.abstract && (
                    <div className="wps-client-input-abstract">{input.abstract}</div>
                )}
                {this.renderInputControl(input, value)}
                {error && <div className="wps-client-field-error">{error}</div>}
            </div>
        );
    };

    renderInputControl = (input, value) => {
        // If there are allowed values, render a ComboBox
        if (input.allowedValues) {
            return (
                <ComboBox
                    onChange={(val) => this.handleInputChange(input.identifier, val)}
                    placeholder="Select a value..."
                    value={value}
                >
                    {input.allowedValues.map(av => (
                        <span key={av} title={av.toString()} value={av.toString()}>
                            {av.toString()}
                        </span>
                    ))}
                </ComboBox>
            );
        }

        // Boolean type
        if (input.dataType === 'boolean') {
            return (
                <ComboBox
                    onChange={(val) => this.handleInputChange(input.identifier, val)}
                    placeholder="Select..."
                    value={value}
                >
                    <span title="true" value="true">True</span>
                    <span title="false" value="false">False</span>
                </ComboBox>
            );
        }

        // Integer or float
        if (input.dataType === 'integer' || input.dataType === 'float') {
            return (
                <NumberInput
                    decimals={input.dataType === 'float' ? 6 : 0}
                    onChange={(val) => this.handleInputChange(input.identifier, val !== null ? val.toString() : '')}
                    value={value !== '' ? parseFloat(value) : null}
                />
            );
        }

        // Default: text input
        return (
            <input
                className="wps-client-text-input"
                onChange={(ev) => this.handleInputChange(input.identifier, ev.target.value)}
                placeholder={input.title}
                type="text"
                value={value}
            />
        );
    };

    renderResults = () => {
        const { results } = this.state;
        if (!results) return null;
        console.log(results)
        return (
            <div className="wps-client-section wps-client-results">
                <label className="wps-client-label">Results:</label>
                <table className="wps-client-results-table">
                    <tbody>
                        {results.map(output => (
                            < tr key={output.identifier} >
                                <td className="wps-client-result-label">{output.title}</td>
                                <td className="wps-client-result-value">{output.value}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div >
        );
    };
}

export default connect(
    () => ({}),
    {
        processStarted: processStarted,
        processFinished: processFinished
    }
)(WpsClient);
