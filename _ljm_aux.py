# Created by Joonseok Hur
# Custom functionsc for labJack control

import numpy as np
from enum import Enum

from labjack import ljm

from typing import TypedDict, Union


# Enums


class LabJackDeviceTypeEnum(Enum):
    """Enum for LabJack device type.
    Refer to https://support.labjack.com/docs/gethandleinfo-ljm-user-s-guide
    """
    T4 = ljm.constants.dtT4  # 4
    T7 = ljm.constants.dtT7  # 7
    T8 = ljm.constants.dtT8  # 8
    DIGIT = ljm.constants.dtDIGIT  # 200


class LabJackConnectionTypeEnum(Enum):
    """Enum for LabJack connection type
    refer to https://support.labjack.com/docs/gethandleinfo-ljm-user-s-guide
    """
    USB = ljm.constants.ctUSB  # 1
    ETHERNET = ljm.constants.ctETHERNET  # 3
    WIFI = ljm.constants.ctWIFI  # 4


class LabJackTriggerModeEnum(Enum):
    """Enum for LabJack trigger modes
    refer to https://support.labjack.com/docs/3-2-2-special-stream-modes-t-series-datasheet#id-3.2.2SpecialStreamModes[T-SeriesDatasheet]-TriggeredStream-T7/T8
    """
    FrequencyIn = 3
    PulseWidthIn = 5
    ConditionalReset = 12


class LabJackTriggerEdgeEnum(Enum):
    """Enum for LabJack trigger edge options
    refer to https://support.labjack.com/docs/13-2-13-conditional-reset-t-series-datasheet#id-13.2.13ConditionalReset[T-SeriesDatasheet]-Configure
    """
    Falling = 0
    Rising = 1
    
class LabJackStreamReturnEnum(Enum):
    """Enum for LabJack trigger edge options
    refer to https://support.labjack.com/docs/ljm-stream-configs#LJMStreamConfigs-LJM_STREAM_SCANS_RETURN
    """
    ljm.constants.STREAM_SCANS_RETURN_ALL = 1
    ljm.constants.STREAM_SCANS_RETURN_ALL_OR_NONE = 2
    


# Errors
# # general
class LabJackError(Exception):
    """Exception for general LabJack errors"""
    pass

# # connection
class LabJackConnectionError(LabJackError):
    """Exception for errors while establishing connection to LabJack"""
    pass

class LabJackNoConnectionError(LabJackError):
    """Exception for errors when no connection to LabJack has been established."""
    pass
class LabJackDisconnectionError(LabJackError):
    """Exception for errors while closing connection to LabJack"""
    pass

# configuration
class LabJackLibraryConfigurationError(LabJackError):
    """Exception for errors while configuring `ljm` library"""
    pass

class LabJackRegisterConfigurationError(LabJackError):
    """Exception for errors while configuring LabJack device register"""
    pass

# stream read
# class LabJackStreamReadConfigurationError(LabJackError):
#     """Exception for errors while configuring labjack or library for stream read"""
#     pass

class LabJackStreamReadError(LabJackError):
    """Exception for errors while stream read"""
    pass




# data handling
def LabJackaData2chData(aData, numAddresses, scanRate=np.nan):
    """sort interleaved data from streaming (refer to https://support.labjack.com/docs/estreamread-ljm-user-s-guide)
    to the 2D array indexed by channel and time order

    Args:
        aData (list or numpy.array): interleaved data returned from streaming
        numAddresses (int): number of input channels streamed
        scanRate (float, optional): scan rate to determine measured time of data. Defaults to np.nan.

    Returns:
        list: list of dict for data per hannel
            dict:
                'V' (np.array of float): measured voltage
                'idx' (np.array of int): index of data in the input streamed data "aData"
                't' (np.array of float, optional): time elapsed for the measurement.
    """
    aData = np.array(aData)

    # chData = [aData[idx::numAddresses] for idx in range(numAddresses)]
    chData = [{} for _ in range(numAddresses)]
    idxs = np.array(range(len(aData)))  # aData index array

    for i in range(numAddresses):
        ichs = idxs[i::numAddresses]
        chData[i]['idx'] = ichs
        chData[i]['V'] = np.array(aData[ichs])
        if scanRate is not np.nan:
            chData[i]['t'] = ichs/scanRate

    return chData


# TypedDict classes
class LabJackConnectionConfigTypedDict(TypedDict):
    deviceType: LabJackDeviceTypeEnum
    connectionType: LabJackConnectionTypeEnum
    deviceIdentifier: Union[str, int]


class LabJackStreamingConfigTypedDict(TypedDict):
    # Input channels
    aScanListNames: list[str]  # Scan list names to stream

    # scan rate & duration
    # scan per second. "Scan" is a set of readings for all channels to stream
    # Therefore, sampling rate is scanRate * numAddresses
    # max sample rate depends on resolution index and voltage range
    # see https://support.labjack.com/docs/a-1-data-rates-t-series-datasheet
    # max scan rate is 100e3 Hz for LabJack T7, single channel, resolution index = 0 or 1, voltage gain = 1
    scanRate: float  # Hz
    # duration of streaming
    scanDuration: float  # second
    # The number of eStreamRead calls that will be performed.
    numReads: int

    # triggering
    doTrigger: bool
    TriggerMode: LabJackTriggerModeEnum
    TriggerEdge: LabJackTriggerEdgeEnum
    TriggerName: str


class LabJackStreamChDataTypedDict(TypedDict):
    V: np.ndarray
    idx: np.ndarray
    t: np.ndarray


class LabJackStreamDataTypedDict(TypedDict):
    aScanListNames: list[str]  # Scan list names to stream

    chData: list[LabJackStreamChDataTypedDict]
    scanRate: float  # Hz
    totScans: int
    skippedScans: int
