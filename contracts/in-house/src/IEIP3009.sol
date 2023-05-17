pragma solidity >=0.5.0;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/**
 * EIP 30009 interface
 */
interface IEIP3009 is IERC20 {

    function receiveWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;

}