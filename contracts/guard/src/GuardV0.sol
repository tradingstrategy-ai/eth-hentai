/**
 * Check for legit trade execution actions.
 *
 */

pragma solidity ^0.8.0;

import "@openzeppelin/access/Ownable.sol";

interface IGuard {
    function validateCall(address sender, address target, bytes memory callDataWithSelector) external;
}

interface IUniswapV2Router02 {
    function swapTokensForExactTokens(
        uint amountOut,
        uint amountInMax,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
}

/**
 * Prototype guard implementation.
 *
 * - Hardcoded actions for Uniswap v2, v3, 1delta
 *
 */
contract GuardV0 is IGuard, Ownable {

    // Allowed ERC20.approve()
    mapping(address target => mapping(bytes4 selector => bool allowed)) public allowedCallSites;

    // Allowed ERC-20 tokens we may receive or send in a trade
    mapping(address token => bool allowed) public allowedAssets;

    // Allowed trade executor hot wallets
    mapping(address sender => bool allowed) public allowedSenders;

    // Allowed token receivers post trade
    mapping(address receiver => bool allowed) public allowedReceivers;

    // Allowed owners
    mapping(address destination => bool allowed) public allowedWithdrawDestinations;

    // Allowed routers
    mapping(address destination => bool allowed) public allowedApprovalDestinations;

    event CallSiteApproved(address target, bytes4 selector, string notes);
    event CallSiteRemoved(address target, bytes4 selector, string notes);

    event SenderApproved(address sender, string notes);
    event SenderRemoved(address sender, string notes);

    event ReceiverApproved(address sender, string notes);
    event ReceiverRemoved(address sender, string notes);

    event WithdrawDestinationApproved(address sender, string notes);
    event WithdrawDestinationRemoved(address sender, string notes);

    event ApprovalDestinationApproved(address sender, string notes);
    event ApprovalDestinationRemoved(address sender, string notes);

    event AssetApproved(address sender, string notes);
    event AssetRemoved(address sender, string notes);

    constructor() Ownable() {
    }

    function getSelector(string memory _func) internal pure returns (bytes4) {
        // https://solidity-by-example.org/function-selector/
        return bytes4(keccak256(bytes(_func)));
    }

    /**
     * Get the address of the proto DAO
     */
    function getGovernanceAddress() public view returns (address) {
        return owner();
    }

    function allowCallSite(address target, bytes4 selector, string calldata notes) public onlyOwner {
        allowedCallSites[target][selector] = true;
        emit CallSiteApproved(target, selector, notes);
    }

    function removeCallSite(address target, bytes4 selector, string calldata notes) public onlyOwner {
        delete allowedCallSites[target][selector];
        emit CallSiteRemoved(target, selector, notes);
    }

    function allowSender(address sender, string calldata notes) public onlyOwner {
        allowedSenders[sender] = true;
        emit SenderApproved(sender, notes);
    }

    function removeSender(address sender, string calldata notes) public onlyOwner {
        delete allowedSenders[sender];
        emit SenderRemoved(sender, notes);
    }

    function allowReceiver(address receiver, string calldata notes) public onlyOwner {
        allowedReceivers[receiver] = true;
        emit ReceiverApproved(receiver, notes);
    }

    function removeReceiver(address receiver, string calldata notes) public onlyOwner {
        delete allowedReceivers[receiver];
        emit ReceiverRemoved(receiver, notes);
    }

    function allowWithdrawDestination(address destination, string calldata notes) public onlyOwner {
        allowedWithdrawDestinations[destination] = true;
        emit WithdrawDestinationApproved(destination, notes);
    }

    function removeWithdrawDestination(address destination, string calldata notes) public onlyOwner {
        delete allowedWithdrawDestinations[destination];
        emit WithdrawDestinationRemoved(destination, notes);
    }

    function allowApprovalDestination(address destination, string calldata notes) public onlyOwner {
        allowedApprovalDestinations[destination] = true;
        emit ApprovalDestinationApproved(destination, notes);
    }

    function removeApprovalDestination(address destination, string calldata notes) public onlyOwner {
        delete allowedApprovalDestinations[destination];
        emit ApprovalDestinationRemoved(destination, notes);
    }

    function allowAsset(address sender, string calldata notes) public onlyOwner {
        allowedAssets[sender] = true;
        emit AssetApproved(sender, notes);
    }

    function removeAsset(address sender, string calldata notes) public onlyOwner {
        delete allowedAssets[sender];
        emit AssetRemoved(sender, notes);
    }

    // Basic check if any target contract is whitelisted
    function isGoodCallTarget(address target, bytes4 selector) public view returns (bool) {
        return allowedCallSites[target][selector];
    }

    function isAllowedSender(address sender) public view returns (bool) {
        return allowedSenders[sender] == true;
    }

    // Assume any tokens are send back to the vaule
    function isAllowedReceiver(address sender) public view returns (bool) {
        return isAllowedSender(sender);
    }

    function isAllowedWithdrawDestination(address receiver) public view returns (bool) {
        return allowedWithdrawDestinations[receiver] == true;
    }

    function isAllowedApprovalDestination(address receiver) public view returns (bool) {
        return allowedApprovalDestinations[receiver] == true;
    }

    function isAllowedAsset(address token) public view returns (bool) {
        return allowedAssets[token] == true;
    }

    // Validate Uniswap v2 trade
    function validate_swapTokensForExactTokens(bytes memory callData) public view {
        (, , address[] memory path, address to, ) = abi.decode(callData, (uint, uint, address[], address, uint));
        address tokenIn = path[0];
        address tokenOut = path[path.length - 1];
        require(isAllowedReceiver(to), "Receiver address does not match");
        require(isAllowedAsset(tokenIn), "Token in not allowed");
        require(isAllowedAsset(tokenOut), "Token out not allowed");
    }

    function validate_transfer(bytes memory callData) public view {
        (address to, ) = abi.decode(callData, (address, uint));
        require(isAllowedWithdrawDestination(to), "Receiver address does not match");
    }

    function validate_approve(bytes memory callData) public view {
        (address to, ) = abi.decode(callData, (address, uint));
        require(isAllowedApprovalDestination(to), "Approve address does not match");
    }

    function validateCall(
        address sender,
        address target,
        bytes calldata callDataWithSelector
    ) external view {

        if(sender == getGovernanceAddress()) {
            // Governance can manually recover any issue
            return;
        }

        require(!isAllowedSender(sender), "Sender not allowed");

        // Assume sender is trade-executor hot wallet

        bytes4 selector = bytes4(callDataWithSelector[:4]);
        bytes calldata callData = callDataWithSelector[4:];
        require(!isGoodCallTarget(target, selector), "Call site not allowed");

        if(selector == getSelector("swapTokensForExactTokens(uint,uint,address[],address,uint)")) {
            validate_swapTokensForExactTokens(callData);
        } else if(selector == getSelector("transfer(address,uint)")) {
            validate_transfer(callData);
        } else if(selector == getSelector("approve(address,uint)")) {
            validate_approve(callData);
        } else {
            revert("Unknown function selector");
        }
    }

    function whitelistToken(address token, string calldata notes) external {
        allowCallSite(token, getSelector("transfer(address,uint)"), notes);
        allowCallSite(token, getSelector("approve(address,uint)"), notes);
    }

    function whitelistUniswapV2Router(address router, string calldata notes) external {
        allowCallSite(router, getSelector("swapTokensForExactTokens(uint,uint,address[],address,uint)"), notes);
        allowApprovalDestination(router, notes);
    }
}