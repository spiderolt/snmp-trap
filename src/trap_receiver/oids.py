from enum import Enum


class Oid(Enum):
    ONU_DESC = "1.3.6.1.4.1.2011.6.128.1.1.2.43.1.9"
    ONU_STATS_STATUS = "1.3.6.1.4.1.2011.6.128.1.1.2.46.1.15"
    ONU_STATS_LAST_DOWN_CAUSE = "1.3.6.1.4.1.2011.6.128.1.1.2.46.1.24"
    ONU_SERIAL = "1.3.6.1.4.1.2011.6.128.1.1.2.49.1.4"
    SNMP_TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
    IF_INDEX = "1.3.6.1.2.1.2.2.1.1"
    IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
    IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
    LINK_DOWN = "1.3.6.1.6.3.1.1.5.3"
    LINK_UP = "1.3.6.1.6.3.1.1.5.4"
    HW_GPON_ONT_LOS_ALARM = "1.3.6.1.4.1.2011.6.128.2.1.4"
    HW_GPON_ONT_LOS_CLEAR = "1.3.6.1.4.1.2011.6.128.2.1.5"
    HW_GPON_ONT_DYING_GASP = "1.3.6.1.4.1.2011.6.128.2.1.6"
    HW_GPON_ONT_DYING_GASP_CLEAR = "1.3.6.1.4.1.2011.6.128.2.1.7"
    HW_GPON_ONT_OFFLINE = "1.3.6.1.4.1.2011.6.128.2.1.8"
    HW_GPON_ONT_ONLINE = "1.3.6.1.4.1.2011.6.128.2.1.9"
    HW_XPON_PORT_LOS = "1.3.6.1.4.1.2011.6.128.2.1.20"
    HW_XPON_PORT_LOS_CLEAR = "1.3.6.1.4.1.2011.6.128.2.1.21"
    HW_GPON_ONT_IF_INDEX = "1.3.6.1.4.1.2011.6.128.1.1.2.43.1.1"
    HW_GPON_ONT_ID = "1.3.6.1.4.1.2011.6.128.1.1.2.43.1.2"


DISCONNECTION_REASONS = {
    "1": "los",
    "2": "los",
    "3": "los",
    "4": "los",
    "5": "los",
    "6": "los",
    "7": "n/a",
    "8": "n/a",
    "9": "reset",
    "10": "reset",
    "11": "n/a",
    "13": "pwr fail",
    "15": "los",
    "18": "n/a",
    "30": "n/a",
    "31": "reset",
    "32": "reset",
    "33": "reset",
    "34": "n/a",
    "35": "n/a",
    "37": "n/a",
    "-1": "n/a",
}
