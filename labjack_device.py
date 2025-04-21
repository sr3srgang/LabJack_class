from labjack import ljm
from _ljm_aux import *
from datetime import datetime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from _stream_in import StreamIn

class LabJackDevice:
    """
    A LabJack device controller that supports triggered streaming.

    Example usage:
    - Connect to a Labjack device
        device = LabJackDevice(device_identifier='192.168.1.120')
        
    - (Triggered) streamed read
        device.stream_read(...)
    
    - Disconnect from the device
        del device # destroying the instance disconnects.
    
    - Using `with` block
        with LabJackDevice(device_identifier='192.168.1.120') as device:
            stream_data = lj.stream()
            # process stream_data ...
    """
    
    # >>>>> class setting >>>>>
    
    # Read-only properties
    @property
    def device_type(self): return self._device_type
    @property
    def connection_type(self): return self._connection_type
    @property
    def device_identifier(self): return self._device_identifier
    @property
    def serial_number(self): return self._serial_number
    @property
    def IP_address(self): return self._IP_address
    @property
    def port(self): return self._port
    @property
    def max_bytes_per_MB(self): return self._max_bytes_per_MB

    def __init__(
            self,
            device_type: LabJackDeviceTypeEnum, 
            connection_type: LabJackConnectionTypeEnum,
            device_identifier: str
        ) -> None:
        """
        Initialize the LabJackDevice.

        Parameters:
            device_type: An enum value indicating the LabJack device type (e.g., LabJackDeviceTypeEnum.T7).
            connection_type: An enum value indicating the connection type (e.g., LabJackConnectionTypeEnum.ETHERNET).
            device_identifier: The device identifier (e.g., IP address or serial number).
        """
        # Connection configuration
        self._device_type = device_type
        self._connection_type = connection_type
        self._device_identifier = device_identifier
        
        self._connect()
        print()
        print(self)
        print()
    
    def __enter__(self) -> None:
        """
        Support for context manager (i.e., "with" keyword).
        """
        self._connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """
        Ensure disconnection when used as a context manager (i.e., "with" keyword).
        Disconnect from the LabJack device if connected when an object is about to be disposed.
        """
        if hasattr(self, '_handle') and self._handle is not None:
            try:
                self._close()
            except Exception:
                pass
        
    def __del__(self) -> None:
        """
        destructor
        Disconnect from the LabJack device if connected when an object is about to be disposed.    
        """
        try:
            self.__exit__(None, None, None)
        except Exception:
            # Don't let destructor crash the interpreter
            pass
        
    def __str__(self) -> str:
        msg = "LabJack device instance:"
        msg += f"\n\tDevice type: {self._device_type.name}"
        msg += f"\n\tConnection type: {self._connection_type.name}"
        msg += f"\n\tIP address: {self._IP_address}, Port: {self._port}"
        msg += f"\n\tSerial number: {self._serial_number}"
        msg += f"\n\tMax bytes per MB: {self._max_bytes_per_MB}"
        return msg
    
    # <<<<< class setting <<<<<
     
        
        
    # >>>>> LabJack connection >>>>>
    
    def _connect(self) -> None:
        """
        Connect to the LabJack device and load device info.
        """
        print(">>> Connecting to LabJack... ", end="")
        
        
        
        # Open device (using names of enums)
        try:
            start = datetime.now()
            self._handle = ljm.openS(self._device_type.name,
                                    self._connection_type.name,
                                    self._device_identifier)
            end = datetime.now()
        except ljm.LJMError as ljmex:
            raise LabJackConnectionError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackConnectionError("Non LabJack library-level error") from ex
            
        td_exe = end - start
        
        # Get device info and store it
        # https://support.labjack.com/docs/gethandleinfo-ljm-user-s-guide
        info = ljm.getHandleInfo(self._handle) # cf. it does not initiate communications with the device
        self._serial_number = info[2]
        self._IP_address = ljm.numberToIP(info[3])
        self._port = info[4]
        self._max_bytes_per_MB = info[5]
        
        
        print(f"Done. Execution time: {td_exe.total_seconds():.6f} s")
        
    def _check_connection(self) -> None:
        if self._handle is None:
            raise LabJackNoConnectionError("LabJack connection handle is not assigned.")
    
    
    def _disconnect(self) -> None:
        """
        Disconnect from the LabJack device and handle errors
        """
        self._check_connection()

        print(f">>> Disconnecting LabJack (SN: {self._serial_number})... ", end="")
        
        # try disconnecting
        
        try:
            # ask ljm library for the disconnetion
            start = datetime.now()
            ljm.close(self._handle)
            end = datetime.now()
            td_exe = end - start
        except ljm.LJMError as ljmex:
            raise LabJackDisconnectionError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackDisconnectionError("Non LabJack library-level error") from ex
        finally:
            self._handle = None
            self._device_info = None

        print(f"Done. Execution time: {td_exe.total_seconds():.6f} s")
        
    # <<<<< LabJack connection <<<<<

    
    
    # >>>>> LabJack configuration >>>>>
    
    def configure_library(self, **kwargs: int | float | str ) -> None:
        """
        Configure `ljm` library.
        
        Refer to https://support.labjack.com/docs/ljm-library-configuration-functions for the list of the configurations.
        
        Args: keyward arguments
        - key                           : configuration name
        - value (int or float or str)   : corresponding value to set
        
        cf. From the link: "Whenever LJM is started up, it is loaded with default values, so any desired configurations must be applied each time LJM is started."
            Refer to `./ljm_startup_configs.json` file and https://support.labjack.com/docs/ljm-startup-configs for the default configuration.
                
        ljm methods used: 
        - https://support.labjack.com/docs/writelibraryconfigs-ljm-user-s-guide
        - https://support.labjack.com/docs/writelibraryconfigstrings-ljm-user-s-guide
        """
        # check connection
        self._check_connection()
        
        # check inputs
        handle = self._handle
        N_config = len(kwargs)
        if N_config < 1:
            raise ValueError("No given configuration.")
        
        for key, value in kwargs.items():
            if isinstance(value, (int, float, str)) is not True:
                raise ValueError(f"LabJack configuration value should be number or string\n\tInput configuration: {key} = {value}")
        
        try:
            for key, value in kwargs.items():
                if isinstance(value, str):
                    # configure string values
                    ljm.writeLibraryConfigStringS(key, value)
                else:
                    ljm.writeLibraryConfigS(key, value)
        except ljm.LJMError as ljmex:
            raise LabJackLibraryConfigurationError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackLibraryConfigurationError("Non LabJack library-level error") from ex
    
    def configure_register(self, *,
                  AIN_ALL_NEGATIVE_CH=ljm.constants.GND,
                  AIN_ALL_RANGE=10.0,
                  **kwargs: int | float | str):
        """
        Configure LabJack device register
        Refer to the following links for the list of the configurations.
        - https://support.labjack.com/docs/t-series-datasheet
        - https://support.labjack.com/docs/3-1-modbus-map-t-series-datasheet
        - https://support.labjack.com/docs/3-1-2-printable-modbus-map
        
        Args: keyward arguments
        - key                           : configuration name
        - value (int or float or str)   : corresponding value to set
        
        Useful examples:
        - AIN<channel number or _ALL>_NEGATIVE_CH = ljm.constants.GND
          Set specified or all the analog channels to be single-ended (i.e., reading referenced to the ground)
          https://support.labjack.com/docs/14-0-analog-inputs-t-series-datasheet#id-14.0AnalogInputs[T-SeriesDatasheet]-Single-endedorDifferential-T7Only
          
          Examples:
            - AIN0_NEGATIVE_CH = ljm.constants.GND
            - AIN_ALL_NEGATIVE_CH = ljm.constants.GND
        
        - AIN<channel number or _ALL>_RANGE = <voltage in V>
          Set specified or all the channel to have +-<voltage in V> as the voltage range 
          https://support.labjack.com/docs/14-0-analog-inputs-t-series-datasheet#id-14.0AnalogInputs[T-SeriesDatasheet]-Range/Gain-T7/T8
          e.g., AIN_ALL_NEGATIVE_CH = 10.0 (cf. LabJack default value)
            
        cf. Unlike `ljm` library configuration, the Modbus register values are not reset from power cycling or new connections
            Relevant references:
        - Factory & Power-up defaults configuration through Kippling app
            https://support.labjack.com/docs/general-configuration#GeneralConfiguration-Power-UpDefaults
        - I/O configuration through programing
            https://support.labjack.com/docs/24-0-io-config-_default-t-series-datasheet
        - Factory default values (search keyword: `power-up default`):
            https://support.labjack.com/docs/15-0-dac-t-series-datasheet#id-15.0DAC[T-SeriesDatasheet]-Power-upDefaults
            https://support.labjack.com/docs/14-0-analog-inputs-t-series-datasheet (default values scattered around...)
            https://support.labjack.com/docs/13-0-digital-i-o-t-series-datasheet#id-13.0DigitalI/O[T-SeriesDatasheet]-Power-upDefaults
            https://support.labjack.com/docs/configuring-reading-a-counter
        
        ljm methods used:
        - https://support.labjack.com/docs/general-configuration
        - https://support.labjack.com/docs/ewritenames-ljm-user-s-guide
        - https://support.labjack.com/docs/ewritenamestring-ljm-user-s-guide
        """
        # check connection
        self._check_connection()
        
        # add specified arguments in the configuration
        kwargs.update({
            "AIN_ALL_NEGATIVE_CH": AIN_ALL_NEGATIVE_CH,
            "AIN_ALL_RANGE": AIN_ALL_RANGE,
        })
        
        # check inputs
        handle = self._handle
        N_config = len(kwargs)
        if N_config < 1:
            raise ValueError("No given configuration.")
        
        for key, value in kwargs.items():
            if isinstance(value, (int, float, str)) is not True:
                raise ValueError(f"LabJack configuration value should be number or string\n\tInput configuration: {key} = {value}")
        
        try:
            keys_number = []; values_number = []
            for key, value in kwargs.items():
                if isinstance(value, str):
                    # configure string values
                    ljm.eWriteNameString(key, value)
                else:
                    keys_number.append(key); values_number.append(value)
            # configure number values
            N_config_number = len(keys_number)
            ljm.eWriteNames(handle, N_config_number, keys_number, values_number)
        except ljm.LJMError as ljmex:
            raise LabJackRegisterConfigurationError("LabJack library-level error") from ljmex
        except Exception as ex:
            raise LabJackRegisterConfigurationError("Non LabJack library-level error") from ex
    
    # <<<<< LabJack configuration <<<<<
    
    
    
    
    # >>>>>>> LabJack operation >>>>>>>
    # to be implemented in a separate protected file (i.e., in ./_XXX.py; class defined in the file does not need to be protected)

    # >>>>> stream in >>>>>
    # implemented in ./_stream_in.py

    # streaming input
    def stream_in(
            self,
            scan_channels: list[str] = ["AIN0", "AIN1", "AIN2"],
            duration_s: int = 1,
            *,
            sampling_rate_Hz: float = 100e3,
            scans_per_read: int | None = None,
            do_trigger: bool =False,
            trigger_channel : str = "DIO0",
            trigger_mode: LabJackTriggerModeEnum = LabJackTriggerModeEnum.ConditionalReset,
            trigger_edge: LabJackTriggerEdgeEnum = LabJackTriggerEdgeEnum.Rising,
        ) -> 'StreamIn':
        """
        configure and initiate (triggered) streaming and return a LabJackDevice.Stream object that contains the result.
        
        Args:
                scan_channels (list of str) : List of analog input channel names to stream
                                            default: ["AIN0", "AIN1", "AIN2"]
                scan_duration_s (float)     : Duration (in seconds) for streaming.
                total_scan_rate_Hz (float)  : Total scan rate over all channel in Hz. defaults: 100e3. 
                                            cf. scan rate per channel = [total_scan_rate_Hz / len(scan_channels)] Hz.
                scans_per_read (int)        : Number of scans over all channel per eStreamRead.
                do_trigger (bool)           : Whether to use triggered streaming.
                trigger_channel (str)       : Name of the trigger channel 
                                            default: "DIO0"
                trigger_mode                : Enum value for the trigger mode.
                                            Default: LabJackTriggerModeEnum.ConditionalReset.
                trigger_edge                : Enum value for the trigger edge.
                                            Default: LabJackTriggerEdgeEnum.Rising

        Returns:
            An LabJackDevice.Stream object
        """
        # check connection
        self._check_connection()
        from _stream_in import StreamIn
        return StreamIn(self, scan_channels, duration_s, \
                sampling_rate_Hz=sampling_rate_Hz, scans_per_read=scans_per_read, \
                do_trigger=do_trigger, trigger_channel=trigger_channel, trigger_mode=trigger_mode, trigger_edge=trigger_edge)
    
    # <<<<< stream in <<<<<
        
    # <<<<<<< LabJack operation <<<<<<<

# example usage
if __name__ == "__main__":
    # connect to LabJack
    lj_device = LabJackDevice(
        device_type=LabJackDeviceTypeEnum.T7,
        connection_type=LabJackConnectionTypeEnum.ETHERNET,
        device_identifier='192.168.1.128',
    )
    
    # # (Optional) configure `ljm` library
    # # If not run, default configuration will be used. Refer to the docstring of LabJackDevice.configure_library() method.
    # lj_device.configure_library()
    
    # (Optional) configure LabJack device register
    # Better to run as the values will be the ones last used or power-up defaults.
    # Refer to the docstring LabJackDevice.configure_register() method.
    lj_device.configure_register(AIN_ALL_NEGATIVE_CH=ljm.constants.GND, AIN_ALL_RANGE=10)
    
    # disconnect from LabJack

    del lj_device