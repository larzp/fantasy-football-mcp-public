"""
Automatic Yahoo API Token Management

This module provides automatic token refresh functionality that runs in the background
and ensures your Yahoo API tokens are always valid without manual intervention.
"""

import asyncio
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from loguru import logger
from dotenv import load_dotenv, set_key

from src.agents.yahoo_auth import YahooAuth, YahooTokens, AuthState
from config.settings import Settings


class AutoTokenManager:
    """
    Automatic token management service that runs in the background
    and handles token refresh automatically.
    """
    
    def __init__(
        self, 
        settings: Settings,
        refresh_buffer_minutes: int = 10,
        check_interval_seconds: int = 300  # Check every 5 minutes
    ):
        """
        Initialize automatic token manager.
        
        Args:
            settings: Application settings
            refresh_buffer_minutes: Refresh tokens this many minutes before expiry
            check_interval_seconds: How often to check token status
        """
        self.settings = settings
        self.refresh_buffer_minutes = refresh_buffer_minutes
        self.check_interval_seconds = check_interval_seconds
        
        # Initialize Yahoo auth
        self.yahoo_auth = YahooAuth(settings)
        
        # Background task control
        self._running = False
        self._background_task: Optional[asyncio.Task] = None
        self._stop_event = threading.Event()
        
        # Status tracking
        self.last_refresh_time: Optional[datetime] = None
        self.refresh_count = 0
        self.last_error: Optional[str] = None
        
        logger.info("AutoTokenManager initialized")
    
    async def start(self) -> None:
        """Start the automatic token management service."""
        if self._running:
            logger.warning("AutoTokenManager is already running")
            return
        
        self._running = True
        self._stop_event.clear()
        
        # Start background task
        self._background_task = asyncio.create_task(self._background_loop())
        
        # Initial token check
        await self._check_and_refresh_tokens()
        
        logger.info("AutoTokenManager started")
    
    async def stop(self) -> None:
        """Stop the automatic token management service."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        
        logger.info("AutoTokenManager stopped")
    
    async def _background_loop(self) -> None:
        """Background loop that periodically checks and refreshes tokens."""
        try:
            while self._running:
                await self._check_and_refresh_tokens()
                
                # Wait for next check or stop signal
                for _ in range(self.check_interval_seconds):
                    if not self._running:
                        break
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.debug("Background token manager loop cancelled")
        except Exception as e:
            logger.error(f"Background token manager error: {e}")
            self.last_error = str(e)
    
    async def _check_and_refresh_tokens(self) -> bool:
        """
        Check token status and refresh if needed.
        
        Returns:
            True if tokens are valid, False if refresh failed
        """
        try:
            # First try to load tokens from environment variables if none exist in storage
            if not self.yahoo_auth.tokens:
                await self._load_tokens_from_env()
            
            # Then try to load from storage
            self.yahoo_auth._load_tokens()
            
            if not self.yahoo_auth.tokens:
                logger.warning("No tokens found - manual authentication required")
                self.last_error = "No tokens found"
                return False
            
            # Check if token needs refresh
            needs_refresh = self._should_refresh_token(self.yahoo_auth.tokens)
            
            if needs_refresh:
                logger.info("Token needs refresh - refreshing automatically")
                
                try:
                    # Refresh tokens
                    new_tokens = await self.yahoo_auth.refresh_tokens()
                    
                    # Update environment file
                    self._update_env_file(new_tokens)
                    
                    # Update Claude config if it exists
                    self._update_claude_config(new_tokens)
                    
                    # Update tracking
                    self.last_refresh_time = datetime.now()
                    self.refresh_count += 1
                    self.last_error = None
                    
                    logger.info(f"Tokens refreshed successfully (#{self.refresh_count})")
                    logger.info(f"New token expires at: {new_tokens.expires_at}")
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"Failed to refresh tokens: {e}")
                    self.last_error = f"Refresh failed: {e}"
                    
                    # If refresh failed with invalid_grant, tokens are permanently expired
                    if "invalid_grant" in str(e).lower():
                        logger.warning("Refresh token expired - manual re-authentication required")
                        self.last_error = "Refresh token expired - manual auth required"
                    
                    return False
            
            else:
                # Token is still valid
                time_until_expiry = self.yahoo_auth.tokens.expires_at - datetime.now()
                logger.debug(f"Token is valid for {time_until_expiry}")
                return True
                
        except Exception as e:
            logger.error(f"Error checking tokens: {e}")
            self.last_error = str(e)
            return False
    
    async def _load_tokens_from_env(self) -> None:
        """Load tokens from environment variables if available."""
        try:
            access_token = os.getenv("YAHOO_ACCESS_TOKEN")
            refresh_token = os.getenv("YAHOO_REFRESH_TOKEN")
            token_time = os.getenv("YAHOO_TOKEN_TIME")
            
            if access_token and refresh_token:
                # Calculate expiry time
                if token_time:
                    try:
                        token_timestamp = float(token_time)
                        # Yahoo tokens typically expire in 1 hour (3600 seconds)
                        expires_at = datetime.fromtimestamp(token_timestamp + 3600)
                    except (ValueError, TypeError):
                        # Default to 1 hour from now if we can't parse the time
                        expires_at = datetime.now() + timedelta(hours=1)
                else:
                    # Default to 1 hour from now
                    expires_at = datetime.now() + timedelta(hours=1)
                
                from src.agents.yahoo_auth import YahooTokens
                self.yahoo_auth.tokens = YahooTokens(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type="Bearer",
                    expires_at=expires_at,
                    scope="fspt-r"
                )
                
                # Update auth state
                from src.agents.yahoo_auth import AuthState
                if expires_at > datetime.now():
                    self.yahoo_auth.auth_state = AuthState.AUTHENTICATED
                else:
                    self.yahoo_auth.auth_state = AuthState.TOKEN_EXPIRED
                
                logger.info(f"Loaded tokens from environment, expires at: {expires_at}")
                
        except Exception as e:
            logger.error(f"Failed to load tokens from environment: {e}")
    
    def _should_refresh_token(self, tokens: YahooTokens) -> bool:
        """
        Determine if token should be refreshed based on expiry time.
        
        Args:
            tokens: Current token information
            
        Returns:
            True if token should be refreshed
        """
        if not tokens:
            return False
        
        # Calculate time until expiry
        time_until_expiry = tokens.expires_at - datetime.now()
        
        # Refresh if token expires within buffer time
        refresh_threshold = timedelta(minutes=self.refresh_buffer_minutes)
        
        return time_until_expiry <= refresh_threshold
    
    def _update_env_file(self, tokens: YahooTokens) -> None:
        """
        Update the .env file with new tokens.
        
        Args:
            tokens: New token information
        """
        try:
            env_path = ".env"
            
            # Update environment variables
            set_key(env_path, "YAHOO_ACCESS_TOKEN", tokens.access_token)
            set_key(env_path, "YAHOO_REFRESH_TOKEN", tokens.refresh_token)
            set_key(env_path, "YAHOO_TOKEN_TIME", str(time.time()))
            
            # Reload environment
            load_dotenv(override=True)
            
            logger.debug("Updated .env file with new tokens")
            
        except Exception as e:
            logger.error(f"Failed to update .env file: {e}")
    
    def _update_claude_config(self, tokens: YahooTokens) -> None:
        """
        Update Claude Desktop config with new tokens.
        
        Args:
            tokens: New token information
        """
        try:
            import json
            config_path = "claude_desktop_config.json"
            
            if not os.path.exists(config_path):
                logger.debug("No Claude config file found, skipping update")
                return
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Update tokens in the fantasy-football server env
            if "mcpServers" in config and "fantasy-football" in config["mcpServers"]:
                if "env" not in config["mcpServers"]["fantasy-football"]:
                    config["mcpServers"]["fantasy-football"]["env"] = {}
                
                config["mcpServers"]["fantasy-football"]["env"]["YAHOO_ACCESS_TOKEN"] = tokens.access_token
                config["mcpServers"]["fantasy-football"]["env"]["YAHOO_REFRESH_TOKEN"] = tokens.refresh_token
                
                # Write back
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                logger.debug("Updated Claude config with new tokens")
            
        except Exception as e:
            logger.error(f"Failed to update Claude config: {e}")
    
    async def force_refresh(self) -> bool:
        """
        Force an immediate token refresh.
        
        Returns:
            True if refresh was successful
        """
        logger.info("Forcing token refresh")
        return await self._check_and_refresh_tokens()
    
    async def get_valid_tokens(self) -> Optional[YahooTokens]:
        """
        Get valid tokens, refreshing if necessary.
        
        Returns:
            Valid tokens or None if unavailable
        """
        try:
            # Ensure we have valid tokens
            await self.yahoo_auth.ensure_authenticated()
            return self.yahoo_auth.tokens
        except Exception as e:
            logger.error(f"Failed to get valid tokens: {e}")
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current status of the token manager.
        
        Returns:
            Dictionary with status information
        """
        auth_status = self.yahoo_auth.get_status()
        
        status = {
            "running": self._running,
            "refresh_count": self.refresh_count,
            "last_refresh_time": self.last_refresh_time.isoformat() if self.last_refresh_time else None,
            "last_error": self.last_error,
            "check_interval_seconds": self.check_interval_seconds,
            "refresh_buffer_minutes": self.refresh_buffer_minutes,
            "auth_status": auth_status
        }
        
        if self.yahoo_auth.tokens:
            time_until_expiry = self.yahoo_auth.tokens.expires_at - datetime.now()
            status["time_until_expiry_seconds"] = int(time_until_expiry.total_seconds())
            status["next_refresh_needed"] = self._should_refresh_token(self.yahoo_auth.tokens)
        
        return status


# Global instance for easy access
_auto_token_manager: Optional[AutoTokenManager] = None


async def get_auto_token_manager(settings: Settings) -> AutoTokenManager:
    """
    Get the global auto token manager instance.
    
    Args:
        settings: Application settings
        
    Returns:
        AutoTokenManager instance
    """
    global _auto_token_manager
    
    if _auto_token_manager is None:
        _auto_token_manager = AutoTokenManager(settings)
        await _auto_token_manager.start()
    
    return _auto_token_manager


async def ensure_valid_tokens(settings: Settings) -> Optional[YahooTokens]:
    """
    Convenience function to ensure we have valid tokens.
    
    Args:
        settings: Application settings
        
    Returns:
        Valid tokens or None if unavailable
    """
    manager = await get_auto_token_manager(settings)
    return await manager.get_valid_tokens()


# Example usage
if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    
    from config.settings import Settings
    
    async def main():
        """Example of automatic token management."""
        settings = Settings()
        manager = AutoTokenManager(settings)
        
        print("Starting automatic token manager...")
        await manager.start()
        
        try:
            # Show initial status
            status = manager.get_status()
            print("\nInitial Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")
            
            # Force a refresh to demonstrate
            print("\nForcing token refresh...")
            success = await manager.force_refresh()
            print(f"Refresh successful: {success}")
            
            # Show updated status
            status = manager.get_status()
            print("\nUpdated Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")
            
            # Keep running for a bit to demonstrate background operation
            print("\nRunning for 30 seconds to demonstrate background operation...")
            await asyncio.sleep(30)
            
        finally:
            print("\nStopping token manager...")
            await manager.stop()
            print("Done!")
    
    # Run example
    asyncio.run(main())