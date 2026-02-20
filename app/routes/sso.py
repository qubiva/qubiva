"""
SSO (Single Sign-On) routes for Qubiva.

SSO config CRUD, SAML login, ACS, SP metadata, debug, and metadata reparse.
"""

import logging
import traceback
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.deps import (
    project_manager,
    sso_manager,
    audit_logger,
    templates,
    get_app_base_url,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/api/v1/org/sso/config")
@permissions(["org_admin"])
async def get_sso_config(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Get SSO configuration for the organization."""
    success, sso_config = await project_manager.get_sso_config()

    if not success:
        raise HTTPException(status_code=500, detail=sso_config)

    if sso_config is None:
        return {"message": "SSO not configured", "config": None}

    return {"config": sso_config}


@router.put("/api/v1/org/sso/config")
@permissions(["org_admin"])
async def update_sso_config(
    sso_config: Models.SSOConfigUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Update or create SSO configuration."""
    username = user.get("username", "unknown")
    success, message = await project_manager.update_sso_config(
        enabled=sso_config.enabled,
        saml_idp_metadata_url=sso_config.saml_idp_metadata_url,
        saml_idp_entity_id=sso_config.saml_idp_entity_id,
        saml_idp_sso_url=sso_config.saml_idp_sso_url,
        saml_idp_slo_url=sso_config.saml_idp_slo_url,
        saml_idp_cert=sso_config.saml_idp_cert,
        access_control=sso_config.access_control,
        attribute_mapping=sso_config.attribute_mapping,
        default_org_roles=sso_config.default_org_roles,
        group_mapping_enabled=sso_config.group_mapping_enabled,
        group_mapping=sso_config.group_mapping,
        auto_provision=sso_config.auto_provision,
    )

    if success:
        await audit_logger.log_event(
            "update_sso_config", username, "sso", "org_sso_config",
            details={"enabled": sso_config.enabled}
        )
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.delete("/api/v1/org/sso/config")
@permissions(["org_admin"])
async def delete_sso_config(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Delete SSO configuration."""
    username = user.get("username", "unknown")
    success, message = await project_manager.delete_sso_config()

    if success:
        await audit_logger.log_event(
            "delete_sso_config", username, "sso", "org_sso_config"
        )
        return {"message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/api/v1/sso/login")
async def initiate_sso_login(request: Request):
    """
    Initiate SAML SSO login flow.
    Redirects user to IdP for authentication.
    """
    try:
        if sso_manager is None:
            raise HTTPException(status_code=503, detail="SSO is not available")

        # Check if SSO is enabled
        if not await sso_manager.is_sso_enabled():
            raise HTTPException(status_code=400, detail="SSO is not enabled for this organization")

        # Get SSO config
        sso_config = await sso_manager.get_sso_config()
        if not sso_config:
            raise HTTPException(status_code=500, detail="SSO configuration not found")

        # NEW: Validate required SAML fields before attempting SAML request
        required_fields = {
            'saml_idp_entity_id': 'IdP Entity ID',
            'saml_idp_sso_url': 'IdP SSO URL',
            'saml_idp_cert': 'IdP Certificate'
        }
        missing_fields = []
        for field, display_name in required_fields.items():
            if not sso_config.get(field):
                missing_fields.append(display_name)

        if missing_fields:
            error_msg = f"SSO configuration is incomplete. Missing: {', '.join(missing_fields)}. "
            error_msg += "Please reconfigure SSO in Admin Settings (Manage SSO page)."
            logger.error(f"SSO config validation failed. Missing fields: {missing_fields}")
            logger.error(f"Current config keys: {list(sso_config.keys())}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Prepare SAML request data for OneLogin library
        forwarded_proto = request.headers.get('x-forwarded-proto', request.url.scheme)
        is_https = forwarded_proto == 'https'

        request_data = {
            'https': 'on' if is_https else 'off',
            'http_host': request.url.hostname,
            'server_port': 443 if is_https else 80,
            'script_name': request.url.path,
            'get_data': dict(request.query_params),
            'post_data': {}
        }

        # Prepare SAML authentication request
        result = sso_manager.prepare_saml_request(request_data, sso_config)

        if not result['success']:
            logger.error(f"Failed to prepare SAML request: {result.get('error')}")
            raise HTTPException(status_code=500, detail="Failed to initiate SSO login")

        # Redirect to IdP
        return RedirectResponse(url=result['sso_url'], status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SSO login initiation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="SSO login failed")


@router.get("/api/v1/org/sso/debug")
@permissions(["org_admin"])
async def debug_sso_config(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """
    Debug endpoint to check SSO configuration status.
    Only accessible to org_admin users.
    """
    try:
        if sso_manager is None:
            return {
                "status": "error",
                "message": "SSO manager not initialized (LOCAL_DEV mode or missing dependencies)"
            }

        # Get SSO config
        success, sso_config = await project_manager.get_sso_config()

        if not success or not sso_config:
            return {
                "status": "not_configured",
                "message": "No SSO configuration found in database"
            }

        # Check which fields are present
        field_status = {
            "enabled": bool(sso_config.get('enabled')),
            "saml_idp_metadata_url": bool(sso_config.get('saml_idp_metadata_url')),
            "saml_idp_entity_id": bool(sso_config.get('saml_idp_entity_id')),
            "saml_idp_sso_url": bool(sso_config.get('saml_idp_sso_url')),
            "saml_idp_slo_url": bool(sso_config.get('saml_idp_slo_url')),
            "saml_idp_cert": bool(sso_config.get('saml_idp_cert')),
            "auto_provision": bool(sso_config.get('auto_provision')),
            "default_org_roles": sso_config.get('default_org_roles', [])
        }

        # Determine overall status
        critical_fields_present = all([
            field_status['saml_idp_entity_id'],
            field_status['saml_idp_sso_url'],
            field_status['saml_idp_cert']
        ])

        if critical_fields_present:
            status = "ready"
            message = "SSO configuration is complete and ready to use"
        else:
            status = "incomplete"
            missing = [k for k, v in field_status.items() if not v and k.startswith('saml_idp_')]
            message = f"SSO configuration is incomplete. Missing: {', '.join(missing)}"

        return {
            "status": status,
            "message": message,
            "field_status": field_status,
            "metadata_url": sso_config.get('saml_idp_metadata_url', 'Not set'),
            "created_at": sso_config.get('created_at'),
            "updated_at": sso_config.get('updated_at')
        }

    except Exception as e:
        logger.error(f"SSO debug endpoint failed: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to check SSO configuration: {str(e)}"
        }


@router.post("/api/v1/org/sso/reparse-metadata")
@permissions(["org_admin"])
async def reparse_metadata(
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """
    Force re-parse of IdP metadata from saved metadata URL.
    Use this if SSO config exists but parsed fields are missing.
    """
    try:
        # Get current SSO config
        success, sso_config = await project_manager.get_sso_config()

        if not success or not sso_config:
            raise HTTPException(status_code=404, detail="No SSO configuration found")

        metadata_url = sso_config.get('saml_idp_metadata_url')
        if not metadata_url:
            raise HTTPException(
                status_code=400,
                detail="No metadata URL found in SSO configuration. Please reconfigure SSO with metadata URL."
            )

        # Re-parse metadata
        logger.info(f"Re-parsing IdP metadata from: {metadata_url}")
        parsed_metadata = await project_manager._parse_idp_metadata(metadata_url)

        # Update SSO config with parsed values
        from app.deps import db_manager
        update_result = await db_manager.update_one_document(
            'org_settings',
            {'setting_type': 'sso'},
            {
                '$set': {
                    'saml_idp_entity_id': parsed_metadata['entity_id'],
                    'saml_idp_sso_url': parsed_metadata['sso_url'],
                    'saml_idp_slo_url': parsed_metadata.get('slo_url'),
                    'saml_idp_cert': parsed_metadata['x509cert'],
                    'updated_at': datetime.utcnow()
                }
            }
        )

        if update_result['modified_count'] > 0:
            return {
                "success": True,
                "message": "Metadata re-parsed and SSO configuration updated successfully",
                "parsed_fields": {
                    "entity_id": parsed_metadata['entity_id'][:50] + "...",
                    "sso_url": parsed_metadata['sso_url'],
                    "slo_url": parsed_metadata.get('slo_url', 'Not provided'),
                    "cert_present": bool(parsed_metadata['x509cert'])
                }
            }
        else:
            return {
                "success": False,
                "message": "Metadata parsed but no changes were made to database"
            }

    except ValueError as e:
        logger.error(f"Metadata parsing failed: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to parse metadata: {str(e)}")
    except Exception as e:
        logger.error(f"Metadata re-parse failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to re-parse metadata: {str(e)}")


@router.post("/api/v1/sso/acs")
async def handle_sso_callback(request: Request, response: Response):
    """
    SAML Assertion Consumer Service (ACS) endpoint.
    Handles SAML response from IdP after user authentication.
    """
    try:
        if sso_manager is None:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "SSO is not available",
                    "sso_enabled": True  # FIXED: Added this
                },
                status_code=503
            )

        # Check if SSO is enabled
        if not await sso_manager.is_sso_enabled():
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "SSO is not enabled",
                    "sso_enabled": False  # FIXED: Added this (disabled since not enabled)
                },
                status_code=400
            )

        # Get SSO config
        sso_config = await sso_manager.get_sso_config()
        if not sso_config:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "SSO configuration error",
                    "sso_enabled": True  # FIXED: Added this
                },
                status_code=500
            )

        # Get form data (SAML response comes as form POST)
        form_data = await request.form()

        # Prepare request data for OneLogin library
        forwarded_proto = request.headers.get('x-forwarded-proto', request.url.scheme)
        is_https = forwarded_proto == 'https'

        request_data = {
            'https': 'on' if is_https else 'off',
            'http_host': request.url.hostname,
            'server_port': 443 if is_https else 80,
            'script_name': request.url.path,
            'get_data': dict(request.query_params),
            'post_data': dict(form_data)
        }

        # Process SAML response
        success, message, user_data = await sso_manager.process_saml_response(request_data, sso_config)

        if not success:
            logger.warning(f"SSO authentication failed: {message}")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "SSO login failed",
                    "sso_enabled": True
                },
                status_code=401
            )

        email = user_data['email']
        saml_groups = user_data['saml_groups']

        # Check if user exists
        user_exists, existing_user = await project_manager.user_exists(email)

        if user_exists:
            # Existing user - check if auth method matches
            if existing_user.get('auth_method') != 'sso':
                logger.warning(f"User {email} exists as local user, blocking SSO login")
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "error": "This account uses local authentication. Please login with your password.",
                        "sso_enabled": True  # FIXED: Added this
                    },
                    status_code=403
                )

            # Check if user is deactivated
            if not existing_user.get('active', True):
                logger.warning(f"Deactivated SSO user {email} attempted login")
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "error": "Your account has been deactivated. Please contact your administrator.",
                        "sso_enabled": True  # FIXED: Added this
                    },
                    status_code=403
                )

            # Update roles based on current SAML groups
            await project_manager.update_sso_user_roles_on_login(email, saml_groups)

        else:
            # New user - auto-provision if enabled
            if not sso_config.get('auto_provision', True):
                logger.warning(f"Auto-provisioning disabled, blocking new SSO user: {email}")
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "error": "Your account has not been provisioned. Please contact your administrator.",
                        "sso_enabled": True  # FIXED: Added this
                    },
                    status_code=403
                )

            # Auto-provision new user
            success, message = await sso_manager.auto_provision_user(email, saml_groups, sso_config)
            if not success:
                logger.error(f"Failed to auto-provision SSO user {email}: {message}")
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "error": "Failed to create your account. Please contact your administrator.",
                        "sso_enabled": True  # FIXED: Added this
                    },
                    status_code=500
                )

        # Create session token
        session_token = await sso_manager.create_sso_session(email)

        # Set cookie and redirect to dashboard
        redirect_response = RedirectResponse(url="/dashboard", status_code=303)
        redirect_response.set_cookie(
            key="session_token", value=session_token, httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )

        logger.info(f"SSO login successful for user: {email}")
        return redirect_response

    except Exception as e:
        logger.error(f"SSO callback failed: {str(e)}")
        logger.error(traceback.format_exc())
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "SSO authentication failed. Please try again or contact your administrator.",
                "sso_enabled": True  # FIXED: Added this
            },
            status_code=500
        )


@router.get("/api/v1/sso/metadata")
async def get_sp_metadata(request: Request):
    """
    Service Provider (SP) metadata endpoint.
    IdP needs this to configure SAML trust relationship.
    """
    try:
        base_url = get_app_base_url()
        if not base_url:
            raise HTTPException(status_code=500, detail="App base URL not configured. Set 'app.base_url' in app config.")

        metadata_xml = f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                     entityID="{base_url}">
    <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true"
                        protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                                     Location="{base_url}/api/v1/sso/acs"
                                     index="1"/>
    </md:SPSSODescriptor>
</md:EntityDescriptor>"""

        return Response(content=metadata_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Failed to generate SP metadata: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate metadata")
