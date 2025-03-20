import numpy as np
from datetime import datetime
import warnings

from labjack import ljm
from ljm_aux import *  # for triggered stream & custom
# Assume the following enums and exceptions are defined/imported appropriately:
# LabJackDeviceTypeEnum, LabJackConnectionTypeEnum,
# LabJackTriggerModeEnum, LabJackTriggerEdgeEnum,
# LabJackConnectionError, LabJackStreamingError

class LabJackDevice:
    """
    A LabJack device controller that supports triggered streaming.

    Example usage:
        with LabJackDevice(device_identifier='192.168.1.120') as lj:
            stream_data = lj.stream()
            # process stream_data ...
    """

    def __init__(self,
                 device_type,
                 connection_type,
                 device_identifier,
                 ch_names=["AIN0", "AIN1", "AIN2"],
                 scan_rate=100e3,
                 scan_duration=1.5,
                 num_reads=1,
                 do_trigger=False,
                 trigger_ch_name="DIO0",
                 trigger_mode=LabJackTriggerModeEnum.ConditionalReset,
                 trigger_edge=LabJackTriggerEdgeEnum.Rising,
                 ):
        """
        Initialize the LabJackDevice.

        Parameters:
            device_type: An enum value indicating the LabJack device type (e.g., LabJackDeviceTypeEnum.T7).
            connection_type: An enum value indicating the connection type (e.g., LabJackConnectionTypeEnum.ETHERNET).
            device_identifier: The device identifier (e.g., IP address or serial number).
            a_scan_list_names (list of str): List of analog input channel names to stream (e.g., ["AIN0", "AIN2"]).
            scan_rate (float): Scan rate per channel. If not provided, defaults to 100e3 / (number of channels).
            scan_duration (float): Duration (in seconds) for streaming.
            num_reads (int): Number of stream reads.
            do_trigger (bool): Whether to use triggered streaming.
            trigger_mode: Enum value for the trigger mode.
                Defaults to LabJackTriggerModeEnum.ConditionalReset.
            trigger_edge: Enum value for the trigger edge.
                Defaults to LabJackTriggerEdgeEnum.Rising.
            trigger_name (str): Name of the trigger channel.
        """
        # Connection configuration
        self.device_type = device_type
        self.connection_type = connection_type
        self.device_identifier = device_identifier

        # Streaming configuration
        self.a_scan_list_names = ch_names
        self.num_channels = len(self.a_scan_list_names)
        self.scan_rate = scan_rate
        self.scan_duration = scan_duration
        self.num_reads = num_reads

        self.do_trigger = do_trigger
        self.trigger_mode = trigger_mode
        self.trigger_edge = trigger_edge
        self.trigger_name = trigger_ch_name

        # Internal state
        self.handle = None
        self.device_info = None
        self.stream_data = {}

    def connect(self):
        """
        Connect to the LabJack device and load device info.
        """
        try:
            print(">>> Connecting to LabJack...")
            start = datetime.now()
            # Open device (using names of enums)
            self.handle = ljm.openS(self.device_type.name,
                                    self.connection_type.name,
                                    self.device_identifier)
            end = datetime.now()
            td_exe = end - start

            # Get device info and store it
            info = ljm.getHandleInfo(self.handle)
            self.device_info = {
                'deviceType': self.device_type,  # already an enum
                'ConnectionType': self.connection_type,
                'SerialNumber': info[2],
                'IPAddress': ljm.numberToIP(info[3]),
                'Port': info[4],
                'MaxBytesPerMB': info[5]
            }

            print(f"<<< Connected to a LabJack with Device type: {self.device_info['deviceType'].name}, "
                  f"Connection type: {self.device_info['ConnectionType'].name}, Serial number: {self.device_info['SerialNumber']}, "
                  f"IP address: {self.device_info['IPAddress']}, Port: {self.device_info['Port']}, "
                  f"Max bytes per MB: {self.device_info['MaxBytesPerMB']}", end=" ")
            print(f"Execution time: {td_exe.total_seconds():.6f} s\n")

        except ljm.LJMError as ljmex:
            self.disconnect()
            raise LabJackConnectionError("LabJack library-level error") from ljmex
        except Exception as e:
            self.disconnect()
            raise LabJackConnectionError("Non LabJack library-level error") from e

    def disconnect(self):
        """
        Disconnect from the LabJack device.
        """
        try:
            print(">>> Disconnecting LabJack...")
            if self.handle is None:
                warnings.warn("No LabJack connection handle assigned.")
                return
            ljm.close(self.handle)
            if self.device_info is not None:
                print(f"<<< LabJack connection closed (SN: {self.device_info['SerialNumber']})\n")
            else:
                print("<<< LabJack connection closed.\n")
        except ljm.LJMError as ljmex:
            raise LabJackConnectionError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackConnectionError("Non LabJack library-level error") from ex
        finally:
            self.handle = None
            self.device_info = None

    def _check_connection(self):
        if self.handle is None:
            raise LabJackConnectionError("LabJack connection handle is not assigned.")

    def _configure_triggered_stream(self):
        """
        Configure the device to wait for a trigger before beginning stream.
        """
        # Get the address of the trigger channel
        address = ljm.nameToAddress(self.trigger_name)[0]
        ljm.eWriteName(self.handle, "STREAM_TRIGGER_INDEX", address)
        # Clear any previous settings on trigger channel's Extended Feature registers
        ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_ENABLE", 0)

        # Pre-configure some trigger modes (Frequency In and Pulse Width In)
        ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_INDEX", 3)  # rising-to-rising edges
        ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_INDEX", 4)  # falling-to-falling edges

        if self.trigger_mode is LabJackTriggerModeEnum.FrequencyIn:
            ef_index = self.trigger_mode.value  # e.g., 3
            ef_index += 0 if self.trigger_edge is LabJackTriggerEdgeEnum.Rising else 1
            ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_INDEX", ef_index)

        if self.trigger_mode is LabJackTriggerModeEnum.PulseWidthIn:
            ef_index = self.trigger_mode.value  # e.g., 5
            # Note: The original code writes to EF_IDEX which may be a typo.
            ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_INDEX", ef_index)

        if self.trigger_mode is LabJackTriggerModeEnum.ConditionalReset:
            ef_index = self.trigger_mode.value  # e.g., 12
            ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_INDEX", ef_index)
            ef_config_a = self.trigger_edge.value
            ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_CONFIG_A", ef_config_a)

        # Enable the trigger
        ljm.eWriteName(self.handle, f"{self.trigger_name}_EF_ENABLE", 1)

    def _configure_ljm_for_triggered_stream(self):
        """
        Configure LJM library settings for triggered stream.
        """
        ljm.writeLibraryConfigS(ljm.constants.STREAM_SCANS_RETURN,
                                ljm.constants.STREAM_SCANS_RETURN_ALL_OR_NONE)
        ljm.writeLibraryConfigS(ljm.constants.STREAM_RECEIVE_TIMEOUT_MS, 0)
        # By default, LJM will time out with an error while waiting for the stream trigger to occur.

    def stream(self):
        """
        Perform the stream reading.
        
        Returns:
            A dictionary containing:
                - aScanListNames: list of channel names
                - scanRate: configured scan rate
                - totScans: total number of scans acquired
                - skippedScans: number of scans skipped
                - chData: data grouped by channels (via LabJackaData2chData)
        """
        self._check_connection()
        handle = self.handle

        # Streaming configuration parameters
        a_scan_list = ljm.namesToAddresses(self.num_channels, self.a_scan_list_names)[0]
        scan_rate = self.scan_rate
        scan_duration = self.scan_duration
        num_reads = self.num_reads

        # Calculate scans per read
        scans_per_read = int(np.ceil(scan_rate * scan_duration))

        # Device configuration for streaming
        # Ensure triggered stream is disabled initially.
        ljm.eWriteName(handle, "STREAM_TRIGGER_INDEX", 0)
        # Enable internally-clocked stream.
        ljm.eWriteName(handle, "STREAM_CLOCK_SOURCE", 0)

        # Set analog inputs’ negative channels, ranges, settling time and resolution.
        names = ["AIN_ALL_NEGATIVE_CH", "AIN0_RANGE", "AIN1_RANGE",
                 "STREAM_SETTLING_US", "STREAM_RESOLUTION_INDEX"]
        values = [ljm.constants.GND, 10.0, 10.0, 0, 0]
        ljm.eWriteNames(handle, len(names), names, values)

        # Configure triggered stream if required.
        if self.do_trigger:
            self._configure_triggered_stream()
            self._configure_ljm_for_triggered_stream()
            print("<<< Triggered streaming set up.")

        # Start streaming
        try:
            ljm.eStreamStart(handle, scans_per_read, self.num_channels, a_scan_list, scan_rate)
        except ljm.LJMError as ljmex:
            ljm.close(handle)
            raise LabJackStreamingError("LabJack library-level error during stream stop") from ljmex
        except Exception as ex:
            ljm.close(handle)
            raise LabJackStreamingError("Non LabJack library-level error during stream stop") from ex
        print(f">>> Streaming started with a scan rate of {scan_rate} Hz")

        # Read stream data for the specified number of reads.
        
        try:
            ret = ljm.eStreamRead(handle)
            print(f">>> Started reading steam...")
            if self.do_trigger:
                print(">>> Waiting for trigger...\n")
            end_time = datetime.now()

        except ljm.LJMError as ljmex:
            raise ljmex
            # # If no scans are returned, continue; otherwise, propagate the error.
            # if ljmex.errorCode != ljm.errorcodes.NO_SCANS_RETURNED:
            #     raise ljmex
            
        print("<<< stream result returned.\n")
        
        # Stop the stream, ensuring that even if errors occurred, we try to clean up.
        try:
            print(">>> Stopping Stream....")
            ljm.eStreamStop(handle)
            print("<<< Stream stopped.\n")
        except ljm.LJMError as ljmex:
            ljm.close(handle)
            raise LabJackStreamingError("LabJack library-level error during stream stop") from ljmex
        except Exception as ex:
            ljm.close(handle)
            raise LabJackStreamingError("Non LabJack library-level error during stream stop") from ex
        
            
        a_data = ret[0]
        scans = len(a_data) / self.num_channels

        # Count skipped samples (indicated by -9999 values)
        N_skip = a_data.count(-9999.0) / self.num_channels

        # print(f"\teStreamRead {i}")
        # Print scan results for each channel.
        ain_str = "".join(
            f"{self.a_scan_list_names[j]} = {a_data[j]:0.5f}, " for j in range(self.num_channels)
        )
        print(f"\t\tscan out of {int(scans)}: {ain_str}")
        print(f"\t\tSamples Skipped = {N_skip:0.0f}, "
                f"Scan Backlogs: Device = {ret[1]}, LJM = {ret[2]}\n")

        # Process raw streamed data into channel-specific data.
        ch_data = LabJackaData2chData(a_data, self.num_channels, scan_rate)
        records = {}
        for inx, a_scan_list_name in enumerate(self.a_scan_list_names):
            records[a_scan_list_name] = ch_data[inx]

        self.stream_data = {
            "ch_names": self.a_scan_list_names,
            "scan_rate": scan_rate,
            "stream_end_time": end_time,
            "skipped_scans": {"device": ret[1], "labjack": ret[2]},
            "records": records
        }

        return self.stream_data

    def __enter__(self):
        """
        Support for context manager.
        """
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Ensure disconnection when used as a context manager.
        """
        self.disconnect()


if __name__ == "__main__":
    from pprint import pprint
    from labjack import ljm  # ensure proper import of enums/exceptions as needed
    lj_device = LabJackDevice(
        device_type=LabJackDeviceTypeEnum.T7,
        connection_type=LabJackConnectionTypeEnum.ETHERNET,
        device_identifier='192.168.1.92',
        ch_names=["AIN10", "AIN13"],
        scan_rate=50e3,
        scan_duration=0.003,
        do_trigger=False,
        trigger_ch_name="DIO1",
        # trigger_mode=None,
        # trigger_edge=None,
    )
    
    lj_device.connect()

    data = lj_device.stream()
    
    lj_device.disconnect()

    # pprint(data)
    pprint(data["records"])