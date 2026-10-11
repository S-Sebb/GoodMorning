import { createClientHandshake as upstream } from '../../vendor/openchamber-relay/handshake.ts';
import { RelayCloseCode } from '../../vendor/openchamber-relay/protocol.ts';

export async function createClientHandshake(hostKey, options = {}) {
  const handshake = await upstream(hostKey, { ...options, batch: true, flowControl: true });
  const handle = handshake.handleText.bind(handshake);
  handshake.handleText = async raw => {
    const action = await handle(raw);
    if (action.type === 'established' && (!action.batch || !action.flowControl)) {
      return { type: 'fail', closeCode: RelayCloseCode.ChannelFailure,
        reason: 'Current relay batching and flow control are required' };
    }
    return action;
  };
  return handshake;
}
