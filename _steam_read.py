from LabJack_device import LabJackDevice
from labjack import ljm
from _ljm_aux import *
import numpy as np
from datetime import datetime
from pprint import pprint, pformat
from copy import deepcopy
from textwrap import indent

class StreamRead:
    """
    Class to take (possibly triggered) stream measurement and store the result.
    Intended to be instantiated and returned by LabJackDevice.stream() method.

    Example usage:
        with LabJackDevice(device_identifier='192.168.1.120') as lj:
            stream_data = lj.stream()
            # process stream_data ...
    """

    # Read-only properties
    # # input
    @property
    def scan_channels(self): return self._scan_channels
    @property
    def scan_duration_input_s(self): return self._scan_duration_input
    @property
    def total_scan_rate_Hz(self): return self._total_scan_rate
    @property
    def scans_per_read_per_channel(self): return self._scans_per_read_per_channel
    @property
    def do_trigger(self): return self._do_trigger
    @property
    def trigger_channel(self): return self._trigger_channel
    @property
    def trigger_mode(self): return self._trigger_mode
    @property
    def trigger_edge(self): return self._trigger_edge
    @property
    def trigger_timeout_s(self): return self._trigger_timeout_s
    # #derived 
    @property
    def scan_duration_s(self): return self._scan_duration
    @property
    def scan_rate_per_channel_Hz(self): return self._scan_rate_per_channel
    @property
    def records(self): return self._records
    @property
    def skipped_total_scans(self): return self._skipped_total_scans

    def __init__(self,
                device: LabJackDevice,
                scan_channels: list[str] = ["AIN0", "AIN1", "AIN2"],
                scan_duration_s: int = 1,
                *,
                total_scan_rate_Hz: float = 100e3,
                scans_per_read_per_channel: int | None = None,
                do_trigger: bool = False,
                trigger_channel : str = "DIO0",
                trigger_mode: LabJackTriggerModeEnum = LabJackTriggerModeEnum.ConditionalReset,
                trigger_edge: LabJackTriggerEdgeEnum = LabJackTriggerEdgeEnum.Rising,
                trigger_timeout_s: float | None = None,
            )  -> None:
        """
        Initialize the LabJackDevice.

        Parameters:
            device: LabJackDevice object.
            scan_channels (list of str) : List of analog input channel names to stream
                                        default: ["AIN0", "AIN1", "AIN2"]
            scan_duration_s (float)     : Duration (in seconds) for streaming.
            total_scan_rate_Hz (float)  : Total scan rate over all channel in Hz. defaults: 100e3. 
                                        cf. scan rate per channel = [total_scan_rate_Hz / len(scan_channels)] Hz.
            scans_per_read              : Number of scans per channel per eStreamRead.
            (int or 'None')             None for max scans (i.e., stream over scan_duration_s at once)
                                        default: None
            do_trigger (bool)           : Whether to use triggered streaming.
                                        default: False
            trigger_channel (str)       : Name of the trigger channel 
                                        default: "DIO0"
            trigger_mode (ljm_aux.      : Enum value for the trigger mode.
            LabJackTriggerModeEnum)     default: LabJackTriggerModeEnum.ConditionalReset.
            trigger_edge (ljm_aux.      : Enum value for the trigger edge.
            LabJackTriggerEdgeEnum)     default: LabJackTriggerEdgeEnum.Rising.
            trigger_timeout_s (float)   : Duration of waiting for trigger
                                        > 0 or None for indefinite wait.
                                        default: None
        """
        
        # Device
        self._device = device
        self._handle = device._handle

        # Streaming configuration
        self._scan_channels = scan_channels
        num_channels = len(self._scan_channels)
        self._num_channels = num_channels
        self._scan_duration_input = float(scan_duration_s)
        self._total_scan_rate = float(total_scan_rate_Hz)
        num_total_scans = int(np.ceil(total_scan_rate_Hz*scan_duration_s)) # make it integer
        scan_duration = num_total_scans/total_scan_rate_Hz # adjust scan duration
        
        # ensure the last scan contains all channels
        num_scans_channel = int(np.ceil(float(num_total_scans)/num_channels))
        num_total_scans = num_scans_channel*num_channels
        self._num_total_scans = num_total_scans
        scan_duration = num_total_scans/total_scan_rate_Hz
        self._scan_duration = scan_duration
                    
        scan_rate_channel = num_scans_channel/scan_duration
        self._scan_rate_per_channel = scan_rate_channel
        
        if scans_per_read_per_channel is None:
            scans_per_read_per_channel = int(scan_rate_channel*scan_duration_s)
        self._scans_per_read_per_channel = scans_per_read_per_channel
        num_reads = int(np.ceil(float(num_scans_channel)/scans_per_read_per_channel))
        self._num_reads = num_reads

        # trigger configuration
        self._do_trigger = do_trigger
        self._trigger_channel = trigger_channel
        self._trigger_mode = trigger_mode
        self._trigger_edge = trigger_edge
        if trigger_timeout_s is not None and trigger_timeout_s <= 0:
            raise ValueError("trigger_timeout_s should be bigger than 0 or 'None' to indefinitely wait for a trigger.")
        if trigger_timeout_s is None:
            trigger_timeout_s = 0
        self._trigger_timeout = trigger_timeout_s
        
        # configure stream
        self._configure()
        
        # configure trigger if enabled
        if self._do_trigger:
            self._configure_trigger()
        
        # perform stream
        self._stream()


    def _configure(self) -> None:
        """
        Device configuration for streaming
        https://support.labjack.com/docs/3-2-stream-mode-t-series-datasheet#id-3.2StreamMode[T-SeriesDatasheet]-ConfiguringAINforStream
        """
        print(f">>> Configuring LabJack for streaming...", end="")
        # register config for stream
        config_resister = {
            # Ensure triggered stream is disabled initially.
            "STREAM_TRIGGER_INDEX": int(0), 
            # Enable internally-clocked stream.
            "STREAM_CLOCK_SOURCE": int(0), 
            # # settling time in microseconds
            # https://support.labjack.com/docs/analog-input-settling-time-app-note#AnalogInputSettlingTime(AppNote)-T7SamplingDetails
            "STREAM_SETTLING_US": int(0), # default: 0
            # The resolution index for stream readings
            # under https://support.labjack.com/docs/a-3-analog-input-t-series-datasheet
            # e.g., https://support.labjack.com/docs/a-3-2-2-t7-noise-and-resolution-t-series-datasheet#A-3-2-2T7NoiseandResolution[T-SeriesDatasheet]-ADCNoiseandResolution
            "STREAM_RESOLUTION_INDEX": int(0),
        }
        
        start = datetime.now()
        self._device.configure_register(**config_resister)
        end = datetime.now()
        td_exe = end - start
        print(f"Done. Execution time: {td_exe.total_seconds():.6f} s")
        print()
        
    
    def _configure_trigger(self) -> None:
        """
        Configure the device for trigger.
        """
        print(f">>> Configuring LabJack for trigger...", end="")
        
        start = datetime.now()
        # library config
        config_library_trigger = {
            ljm.constants.STREAM_SCANS_RETURN: ljm.constants.STREAM_SCANS_RETURN_ALL,
            ljm.constants.STREAM_RECEIVE_TIMEOUT_MS: self._trigger_timeout,
        }
        self._device.configure_library(**config_library_trigger)
        
        # register config
        # # Clear any previous settings on trigger channel's Extended Feature registers
        self._device.configure_register(**{f"{self._trigger_channel}_EF_ENABLE": 0})
        
        config_register_trigger = {}
        # # Get the address of the trigger channel
        address = ljm.nameToAddress(self._trigger_channel)[0]
        config_register_trigger["STREAM_TRIGGER_INDEX"] = address

        # # Pre-configure some trigger modes (Frequency In and Pulse Width In)
        config_register_trigger[f"{self._trigger_channel}_EF_INDEX"] = 3 # rising-to-rising edges
        config_register_trigger[f"{self._trigger_channel}_EF_INDEX"] = 4 # falling-to-falling edges

        if self._trigger_mode is LabJackTriggerModeEnum.FrequencyIn:
            ef_index = self._trigger_mode.value  # e.g., 3
            ef_index += 0 if self._trigger_edge is LabJackTriggerEdgeEnum.Rising else 1
            config_register_trigger[f"{self._trigger_channel}_EF_INDEX"] = ef_index

        if self._trigger_mode is LabJackTriggerModeEnum.PulseWidthIn:
            ef_index = self._trigger_mode.value  # e.g., 5
            # Note: The original code writes to EF_IDEX which may be a typo.
            config_register_trigger[f"{self._trigger_channel}_EF_INDEX"] = ef_index

        if self._trigger_mode is LabJackTriggerModeEnum.ConditionalReset:
            ef_index = self._trigger_mode.value  # e.g., 12
            config_register_trigger[f"{self._trigger_channel}_EF_INDEX"] = ef_index
            ef_config_a = self._trigger_edge.value
            config_register_trigger[f"{self._trigger_channel}_EF_CONFIG_A"] = ef_config_a
        
        self._device.configure_register(**config_register_trigger)
            
        # #  Enable the trigger
        self._device.configure_register(**{f"{self._trigger_channel}_EF_ENABLE": 1})
        
        end = datetime.now()
        td_exe = end - start
        
        print(f"Done. Execution time: {td_exe.total_seconds():.6f} s")
        print()
        

    def _stream(self) -> None:
        """
        Perform the stream reading and store the result in this instance.
        """
        
        handle = self._handle

        # Streaming configuration parameters
        scansPerRead = self._scans_per_read_per_channel
        NumAddresses = self._num_channels
        aScanList = ljm.namesToAddresses(self._num_channels, self._scan_channels)[0]
        scanRate = self._scan_rate_per_channel
        numReads = self._num_reads
        
        # Start streaming
        # wait for trigger before streaming if enabled
        print(f">>> Streaming starting...", end="")
        try:
            ljm.eStreamStart(handle, scansPerRead, NumAddresses, aScanList, scanRate)
        except ljm.LJMError as ljmex:
            raise LabJackStreamReadError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackStreamReadError("Non LabJack library-level error") from ex
        
        print(f"Started.")

        if self._do_trigger:
            print("\tWaiting for trigger...")

        total_scans = 0
        scans_per_channel = 0
        skipped_total_scans = 0
        total_data = []  # Accumulate data across reads
        start_time = datetime.now()
        timestamp_read_returned = [None]*numReads

        # Read stream data for the specified number of reads.
        ir = 0
        try:
            while ir < numReads:
            # for ir in numReads:
                # read stream from LabJack
                try:
                    ret = ljm.eStreamRead(handle)
                    current_timestamp_read_end = datetime.now()
                except ljm.LJMError as ljmex:
                    # If no scans are returned, continue; otherwise, propagate the error.
                    if ljmex.errorCode == ljm.errorcodes.NO_SCANS_RETURNED:
                        continue
                    raise ljmex
                
                a_data = ret[0] # stream data read
                device_scan_backlog = ret[1]
                ljm_scan_backlog = ret[2]
                
                # Count skipped samples (indicated by -9999 values)
                current_skipped_total_scans = a_data.count(-9999.0)
                skipped_total_scans += current_skipped_total_scans
                
                # conver skipped samples to np.nan
                a_data[a_data == -9999] = np.nan
                
                # add stream data of current eStreamRead
                total_data.extend(a_data) 
                
                # time that data was returned from eStreamRead
                timestamp_read_returned[ir] = current_timestamp_read_end 
                
                current_total_scans = len(a_data)
                total_scans += current_total_scans
                current_scans_per_channel = current_total_scans / self._num_channels
                scans_per_channel += current_total_scans
                

                print(f"\teStreamRead {ir + 1} out of {numReads} returned at {current_timestamp_read_end}.")
                # Print first scan results for each channel.
                # ain_str = "".join(
                #     f"{self._scan_channels[j]} = {a_data[j]:0.5f}, " for j in range(self._num_channels)
                # )
                # print(f"\t\t1st scan out of {int(current_scans_per_channel)}: {ain_str}")
                print(f"\t\tScans Skipped across channels = {current_skipped_total_scans:0.0f}, "
                    f"Scan Backlogs: Device = {device_scan_backlog}, LJM = {ljm_scan_backlog}\n")

                ir += 1
                
            print(f"\tTotal scans = {total_scans}")
            print(f"\tSkipped scans across channels = {skipped_total_scans:0.0f}\n")
        except ljm.LJMError as ljmex:
            raise LabJackStreamReadError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackStreamReadError("Non LabJack library-level error") from ex
        finally:
            # Stop the stream
            print(">>> Stopping Stream....", end="")
            try:
                ljm.eStreamStop(handle)
            except ljm.LJMError as ljmex:
                raise LabJackStreamReadError("LabJack library-level error") from ljmex
            except Exception as ex:
                raise LabJackStreamReadError("Non LabJack library-level error") from ex
            print("Done.\n")

        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()

        # Process raw streamed data into channel-specific data.
        ch_data = LabJackaData2chData(total_data, self._num_channels, scanRate)
        records = {}
        for inx, a_scan_list_name in enumerate(self._scan_channels):
            ch_data_channel = deepcopy(ch_data[inx])
            ch_data_channel.pop('idx')
            records[a_scan_list_name] = ch_data_channel
        
        # store result to this instance    
        self._records = records
        self._skipped_total_scans = skipped_total_scans
        
    def __str__(self) -> str:
        msg = ""
        msg += "Labjack streamed read data:"
        msg += f"\n\trecords = \n"
        msg += indent(pformat(self.records), "\t\t")
        msg += f"\n\tduration = {self.scan_duration_s} s"
        msg += f"\n\tsampling rate ="
        msg += f"\n\t\t{self.total_scan_rate_Hz} total samples/s"
        msg += f"\n\t\t{self.scan_rate_per_channel_Hz} samples/s/channel"
        msg += f"\n\ttriggered = {self.do_trigger}"
        if self._do_trigger:
            msg += f"\n\t\ttrigger channel = {self.trigger_channel}"
            msg += f"\n\t\ttrigger mode = {self.trigger_mode.name}"
            msg += f"\n\t\ttrigger edge = {self.trigger_edge.name}"
        return msg
        
if __name__ == "__main__":
    
    
    lj_device = LabJackDevice(
        device_type=LabJackDeviceTypeEnum.T7,
        connection_type=LabJackConnectionTypeEnum.ETHERNET,
        device_identifier='192.168.1.92',
    )
    
    lj_device._connect()

    streamRead = lj_device.stream_read(["AIN0", "AIN1"], 1)
    print(streamRead)
    print()
    
    lj_device._disconnect()