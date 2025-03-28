from labjack_device import LabJackDevice
from labjack import ljm
from _ljm_aux import *

import asyncio
import threading
import queue

import numpy as np
from datetime import datetime
from pprint import pprint, pformat
from copy import deepcopy
from textwrap import indent
import warnings

class StreamIn:
    """
    Class to take (possibly triggered) stream measurement and store the result.
    Intended to be instantiated and returned by LabJackDevice.stream_in() method.

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
    def duration_input_s(self): return self._duration_input
    @property
    def sampling_rate_Hz(self): return self._sampling_rate
    @property
    def scan_rate_Hz(self): return self._scan_rate
    @property
    def scans_per_read(self): return self._scans_per_read
    @property
    def do_trigger(self): return self._do_trigger
    @property
    def trigger_channel(self): return self._trigger_channel
    @property
    def trigger_mode(self): return self._trigger_mode
    @property
    def trigger_edge(self): return self._trigger_edge
    @property
    def trigger_timeout_s(self): return self._trigger_timeout
    # #derived 
    @property
    def duration_s(self): return self._duration
    @property
    def scan_rate_Hz(self): return self._scan_rate
    @property
    def num_samples(self): return self._num_samples
    @property
    def num_scans(self): return self._num_scans
    _records = None
    @property
    def records(self): return self._records
    @property
    def skipped_samples(self): return self._skipped_samples

    def __init__(self,
                device: LabJackDevice,
                scan_channels: list[str] = ["AIN0", "AIN1", "AIN2"],
                duration_s: int = 1,
                *,
                sampling_rate_Hz: float = 100e3,
                scans_per_read: int | None = None,
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
            duration_s (float)     : Duration (in seconds) for streaming.
            sampling_rate_Hz (float)  : sampling rate (over all channel) in Hz. defaults: 100e3. 
                                        cf. scan rate (per channel) = [sampling_rate_Hz / len(scan_channels)] Hz.
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
        self._duration_input = float(duration_s)
        self._sampling_rate = float(sampling_rate_Hz)
        self._scan_rate = scan_rate_Hz = sampling_rate_Hz/num_channels
        self._num_samples = num_samples = int(np.ceil(sampling_rate_Hz*duration_s)) # make it integer
        self._duration = duration = num_samples/sampling_rate_Hz # adjust scan duration
        
        # ensure the last scan contains all channels
        self._num_scans = num_scans = int(np.ceil(float(num_samples)/num_channels))
        self._duration = duration = num_scans/scan_rate_Hz
        self._num_samples = num_samples = num_scans*num_channels        
        
        if scans_per_read is None:
            scans_per_read = int(scan_rate_Hz*duration_s)
        self._scans_per_read = scans_per_read
        num_reads = int(np.ceil(float(num_scans)/scans_per_read))
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
        # self._records_ready = threading.Event()  # 🔹 marks readiness of stream result
        self._stream_in()


    def _configure(self) -> None:
        """
        Device configuration for streaming
        https://support.labjack.com/docs/3-2-stream-mode-t-series-datasheet#id-3.2StreamMode[T-SeriesDatasheet]-ConfiguringAINforStream
        """
        print(f">>> Configuring LabJack for streaming... ", end="")
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
        # self._device.configure_register(**config_resister)
        try:
            self._device.configure_register(**config_resister)
        except LabJackRegisterConfigurationError as ex:
            # op stream if stream was active
            # labjack.ljm.ljm.LJMError: LJM library error code 2605 STREAM_IS_ACTIVE
            if ex.__cause__ and \
                isinstance(ex.__cause__, ljm.LJMError) and \
                ex.__cause__.errorCode == 2605:
                warnings.warn("Stream was active. Attempting to stop stream... ", category='UserWarning')
                ljm.eStreamStop(self._handle)
                warnings.warn("Stream stopped.", category='UserWarning')
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
        
    
    def _stack_stream_reads(self, 
                                  ir: int, 
                                  timestamp_read_return: datetime,
                                  ret: tuple[list[float], int, int],
                                  ) -> None:
        """
        stack the return of each eStreamRead() to this instance.
        Intended to be asyncio.queue'd in _stream() method.
        """
        a_data = np.array(ret[0]) # stream data read
        device_scan_backlog = ret[1]
        ljm_scan_backlog = ret[2]
        
        # Count skipped samples (indicated by -9999 values)
        skipped_samples = np.sum(a_data == -9999.0)
        self._skipped_samples += skipped_samples
        
        # conver skipped samples to np.nan
        a_data[a_data == -9999.0] = np.nan
        
        # add stream data of current eStreamRead
        self._total_a_data.extend(a_data) 
        
        # time that data was returned from eStreamRead
        self._timestamp_read_return[ir] = timestamp_read_return
        
        current_samples = len(a_data)
        self._samples += current_samples
        current_scans = int(current_samples / self._num_channels)
        self._scans += current_scans
        
        msg = f"\teStreamRead {ir + 1} out of {self._num_reads} returned at {timestamp_read_return}."
        msg += f"\n\t\tScans Skipped across channels = {skipped_samples:0.0f}, "
        msg += f"Scan Backlogs: Device = {device_scan_backlog}, LJM = {ljm_scan_backlog}\n"
        print(msg, flush=True)
        
    # def _queue_worker(self) -> None:
    #     while True:
    #         item = self._queue.get()
    #         if item is None:
    #             break  # signal to exit
    #         ir, timestamp_read_return, ret = item
    #         asyncio.run(self._stack_stream_reads(ir, timestamp_read_return, ret))
    #         self._queue.task_done()
    def _queue_worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break  # signal to exit
            ir, timestamp_read_return, ret = item
            self._stack_stream_reads(ir, timestamp_read_return, ret)
            self._queue.task_done()
    
    async def _run_stream_in(self) -> None:
        """
        Perform the stream reading and store the result in this instance.
        """
        
        handle = self._handle
        
        # # stop streaming if already active
        # try:
        #     # is_streaming = bool(ljm.eReadName(handle, "STREAM_RUNNING"))
        #     is_streaming = bool(ljm.eReadAddress(handle, 44990, ljm.constants.UINT32))
        # except ljm.LJMError as ljmex:
        #     raise LabJackStreamReadError("LabJack library-level error") from ljmex
        # except Exception as ex:
        #     raise LabJackStreamReadError("Non LabJack library-level error") from ex
        # if is_streaming:
        #     warnings.warn("Stream was active. Attempting to stop stream... ", category='UserWarning')
        #     ljm.eStreamStop(self._handle)
        #     warnings.warn("Stream stopped.", category='UserWarning')

        # Streaming configuration parameters
        scansPerRead = self._scans_per_read
        NumAddresses = self._num_channels
        aScanList = ljm.namesToAddresses(self._num_channels, self._scan_channels)[0]
        scanRate = self._scan_rate
        numReads = self._num_reads
        
        # Start streaming
        # wait for trigger before streaming if enabled
        print(f">>> Streaming starting... ", end="", flush=True)
        stream_started = False
        try:
            ljm.eStreamStart(handle, scansPerRead, NumAddresses, aScanList, scanRate)
            stream_started = True  # set after successful eStreamStart()
        except ljm.LJMError as ljmex:
            raise LabJackStreamReadError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackStreamReadError("Non LabJack library-level error") from ex
        finally:
            if stream_started is not True:
                # attempt to stop stream in case the device started streaming
                print("Stream failed to start. Attempting to stop stream... ", end="", flush=True)
                try:
                    ljm.eStreamStop(handle)
                except ljm.LJMError as ljmex:
                    print("Failed.", flush=True)
                    raise LabJackStreamReadError("LabJack library-level error") from ljmex
                except Exception as ex:
                    print("Failed.", flush=True)
                    raise LabJackStreamReadError("Non LabJack library-level error") from ex
                else:
                    print("Done.", flush=True)
                    
        
        print(f"Started.", flush=True)

        if self._do_trigger:
            print("\tWaiting for trigger...", flush=True)

        self._samples = 0
        self._scans = 0
        self._skipped_samples = 0
        self._total_a_data = []  # Accumulate data across reads
        self._timestamp_read_return = [None]*numReads

        # Read stream data for the specified number of reads.
        self._queue = queue.Queue()
        worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
        worker_thread.start()
        
        start_time = datetime.now()
        ir = 0
        try:
            while ir < numReads:
            # for ir in numReads:
                # read stream from LabJack
                try:
                    ret = ljm.eStreamRead(handle)
                    timestamp_read_return = datetime.now()
                except ljm.LJMError as ljmex:
                    # If no scans are returned, continue; otherwise, propagate the error.
                    if ljmex.errorCode == ljm.errorcodes.NO_SCANS_RETURNED:
                        continue
                    raise ljmex
                
                # stack the return of each eStreamRead() to this instance
                self._queue.put((ir, timestamp_read_return, ret))

                ir += 1

        except ljm.LJMError as ljmex:
            raise LabJackStreamReadError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackStreamReadError("Non LabJack library-level error") from ex
        finally:
            # Stop the stream
            print(">>> Stopping Stream...\n", flush=True)
            try:
                ljm.eStreamStop(handle)
            except ljm.LJMError as ljmex:
                raise LabJackStreamReadError("LabJack library-level error") from ljmex
            except Exception as ex:
                raise LabJackStreamReadError("Non LabJack library-level error") from ex
            print("<<< Stream stopped.\n", flush=True)
            
        # wait until data stacking is done
        self._queue.put(None)  # signal to stop thread
        worker_thread.join()   # wait for worker to clean up
        
        msg = f"\t# scans = {self._samples} total, {self._scans}/channel"
        msg += f"\tSkipped scans across channels = {self._skipped_samples:0.0f}\n"
        print(msg, flush=True)

        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()

        # Process raw streamed data into channel-specific data.
        ch_data = LabJackaData2chData(self._total_a_data, self._num_channels, scanRate)
        records = {}
        for inx, a_scan_list_name in enumerate(self._scan_channels):
            ch_data_channel = deepcopy(ch_data[inx])
            ch_data_channel.pop('idx')
            records[a_scan_list_name] = ch_data_channel
        
        # store result to this instance    
        self._records = records
        # self._records_ready.set()  # signal that records are ready
        
        
    def _stream_in(self):
        # """Synchronous method that blocks until async stream finishes."""
        # try:
        #     loop = asyncio.get_running_loop()
        # except RuntimeError:
        #     asyncio.run(self._run_stream_in())
        # else:
        #     # In Jupyter or any already-running loop
        #     done_event = threading.Event()
        #     result_holder = {}
        #     def run_and_signal():
        #         async def wrapper():
        #             await self._run_stream_in()
        #             done_event.set()
        #         asyncio.ensure_future(wrapper())
        #     loop.call_soon_threadsafe(run_and_signal)

        """Synchronous method that blocks until streaming finishes.
        Works in both scripts and interactive (Jupyter/async) environments.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop: script mode
            asyncio.run(self._run_stream_in())
        else:
            # Running loop (Jupyter, async app): use threading.Event to block
            done_event = threading.Event()

            def run_and_signal():
                async def wrapper():
                    await self._run_stream_in()
                    done_event.set()
                asyncio.ensure_future(wrapper())

            loop.call_soon_threadsafe(run_and_signal)
            # done_event.wait()
            # timeout = float(max([10, self._duration*1.5]))
            # if not done_event.wait(timeout=timeout):  # wait max 60s
            #     raise TimeoutError(f"StreamIn._stream_in() did not complete within {timeout} seconds.")
    
    # async def _wait_for_records(self):
    #     while self._records is None:
    #         pass     
        
    def __str__(self) -> str:
        # if self._records is None:
        #     warnings.warn("StreamIn object is not yet ready. Waiting for records...", category=UserWarning)
        #     self._records_ready.wait()
        msg = ""
        msg += "Labjack streamed read data:"
        msg += f"\n\trecords = \n"
        msg += indent(pformat(self.records), "\t\t")
        msg += f"\n\tduration = {self.duration_s} s"
        msg += f"\n\tsampling rate = {self.sampling_rate_Hz} total samples/s, {self.scan_rate_Hz} samples/s/channel"
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

    # # works
    # stream_in = lj_device.stream_in(["AIN0", "AIN1"], 5, sampling_rate_Hz=50e3, scans_per_read=50000)
    # # works
    # stream_in = lj_device.stream_in(["AIN0", "AIN1"], 10, sampling_rate_Hz=50e3)
    # works
    # stream_in = lj_device.stream_in(["AIN0", "AIN1"], 1, sampling_rate_Hz=50e3)
    # # too high sampling rate
    # stream_in = lj_device.stream_in(["AIN0", "AIN1"], 10, sampling_rate_Hz=100e3, scans_per_read=50000)
    # # so sampling rate of 50e3 or below seems a safe choice.
    
    # triggered stream
    stream_in = lj_device.stream_in(["AIN0", "AIN1"], 1, sampling_rate_Hz=50e3, do_trigger=True)
    
    print(stream_in)
    print()
    total_nans = np.sum([np.isnan(value['V']).sum() for value in stream_in.records.values()])
    print(f"Recounting skipped total samples = {total_nans}")
    
    del lj_device
    
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    n_skip_head = 2000
    for channel, record in stream_in.records.items():
        ax.plot(record["t"][n_skip_head:], record["V"][n_skip_head:], label=channel)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title("LabJack Stream In")
    ax.grid(True)
    ax.legend()
    
    fig.savefig("stream_in.png")