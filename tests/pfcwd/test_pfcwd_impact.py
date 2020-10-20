#### Test
import time
import datetime
import pytest
import logging

from abstract_open_traffic_generator.result import FlowRequest
from abstract_open_traffic_generator.control import *

from tests.common.helpers.assertions import pytest_assert

from tests.common.fixtures.conn_graph_facts import conn_graph_facts,\
    fanout_graph_facts

from tests.common.ixia.ixia_fixtures import ixia_api_serv_ip, \
    ixia_api_serv_user, ixia_api_serv_passwd, ixia_dev, ixia_api_serv_port,\
    ixia_api_serv_session_id, api

from files.configs.pfc_wd import pfcwd_configs, ports_config, pfcwd_impact_configs
from files.qos_fixtures import lossless_prio_dscp_map_with_interface

logger = logging.getLogger(__name__)

START_DELAY = [1]
TRAFFIC_LINE_RATE = [50]
FRAME_SIZE = [1024]
STORM_DETECTION_TIME = [400]
STORM_RESTORATION_TIME = [2000]
TOLERANCE_PERCENT = [1]

@pytest.mark.parametrize('frame_size', FRAME_SIZE)
@pytest.mark.parametrize('start_delay', START_DELAY)
@pytest.mark.parametrize('traffic_line_rate', TRAFFIC_LINE_RATE)
@pytest.mark.parametrize('storm_detection_time', STORM_DETECTION_TIME)
@pytest.mark.parametrize('storm_restoration_time', STORM_RESTORATION_TIME)
@pytest.mark.parametrize('tolerance_percent', TOLERANCE_PERCENT)
def test_pfcwd_impact(api,
                     duthost,
                     pfcwd_impact_configs,
                     lossless_prio_dscp_map_with_interface,
                     start_delay,
                     storm_detection_time,
                     storm_restoration_time,
                     tolerance_percent):

    """
    +-----------------+           +--------------+           +-----------------+       
    | Keysight Port 1 |------ et1 |   SONiC DUT  | et2 ------| Keysight Port 2 | 
    +-----------------+           +--------------+           +-----------------+ 

    Configuration:
    1. Configure lossless priorities on the DUT interface.
    2. Disable PFC Watch dog.
    3. On Keysight Chassis, create one unidirectional traffic with lossless priorities and
       one unidirectional traffic with lossy priorities with 50% line rate each.
    
    # Workflow
    1. Start both lossless and lossy traffic on Keysight ports.
    2. Verify the traffic when pfc disabled state.
    3. Wait for 5 seconds and Enable the PFC watch dog on DUT.
    4. Verify the traffic when pfc enabled state.
    5. Disable PFC on DUT.
    6. verify the traffic when pfc disabled state again.
    
    Traffic Verfication:
        In all above traffic verification, No traffic loss and No change in line rate shall be observed.
    """

    #######################################################################
    # Saving the DUT Configuration in variables and disabling pfcwd
    #######################################################################
    # duthost.shell('sudo pfcwd stop')

    dut_cmd_disable = 'sudo pfcwd stop'
    dut_cmd_enable = 'sudo pfcwd start --action drop ports all detection-time {} \
           --restoration-time {}'.format(storm_detection_time,storm_restoration_time)
    duthost.shell(dut_cmd_disable)
    duthost.shell('pfcwd show config')

    #######################################################################
    # TGEN Config and Traffic Test on lossless and lossy
    #######################################################################

    configs = pfcwd_impact_configs(lossless_prio_dscp_map_with_interface)
    for config in configs:
        api.set_state(State(ConfigState(config=config, state='set')))         

        ##############################################################################################
        # Start all flows 
        # 1. check for no loss in the flows Traffic 1->2 lossless,Traffic 1->2 lossy
        # 2. configure pfcwd on dut and wait for 5 seconds
        # 3. check for no loss in the flows configured
        ##############################################################################################
        logger.info("Starting the traffic")
        api.set_state(State(FlowTransmitState(state='start')))

        def check_flow_state():
            for i in range(100):
                test_stat = api.get_flow_results(FlowRequest())
                if "started" in test_stat[0]['transmit']:
                    break
                time.sleep(3)

        def verify_traffic(expected_loss, pfc_state):
            test_stat = api.get_flow_results(FlowRequest())
            for flow in test_stat:
                if flow['loss'] > expected_loss:
                    pytest_assert(False, 
                                  "Observing loss in the flow {} while pfcwd state {}"
                                  .format(flow['name'],pfc_state))
                logger.info("Actual Loss %: {} and Expected Loss: {}".format(flow['loss'], expected_loss))
                tx_frame_rate = int(flow['frames_tx_rate'])
                rx_frame_rate = int(flow['frames_rx_rate'])
                tolerance = (tx_frame_rate * tolerance_percent)/100
                logger.info("\nTx Frame Rate,Rx Frame Rate of {} is {},{}"
                            .format(flow['name'],tx_frame_rate,rx_frame_rate))
                if tx_frame_rate > (rx_frame_rate + tolerance):
                    pytest_assert(False,
                                "Observing traffic rate change in the flow {} while pfcwd state {}"
                                .format(flow['name'],pfc_state))

        logger.info("STEP1: Verify the traffic, No loss Expected on all Priorities while PFCWD is disabled")
        verify_traffic(0.0, 'disabled')
        logger.info("Sleeping for 5 seconds")
        time.sleep(5)
        logger.info("STEP2: Enabling PFCWD")
        duthost.shell(dut_cmd_enable)
        logger.info("STEP3: Verify the traffic, No loss Expected on all Priorities while PFCWD is enabled")
        verify_traffic(0.0, 'enabled')
        logger.info("STEP4: Verify the traffic, No loss Expected on all Priorities while PFCWD is disabled")
        duthost.shell(dut_cmd_disable)
        verify_traffic(0.0, 'disabled')

        logger.info("Stopping the traffic")
        api.set_state(State(FlowTransmitState(state='stop')))